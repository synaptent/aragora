"""
Debate Endpoints (FastAPI v2).

Migrated from: aragora/server/handlers/debates/ (aiohttp handler)

Provides async debate management endpoints:
- GET    /api/v2/debates                              - List debates with pagination
- POST   /api/v2/debates                              - Create a new debate
- GET    /api/v2/debates/{debate_id}                  - Get debate by ID
- GET    /api/v2/debates/{debate_id}/messages         - Get debate messages
- GET    /api/v2/debates/{debate_id}/convergence      - Get convergence status
- GET    /api/v2/debates/{debate_id}/export/{format}  - Export debate in format
- GET    /api/v2/debates/{debate_id}/argument-graph   - Get argument graph
- GET    /api/v2/debates/{debate_id}/stats            - Get graph statistics
- PATCH  /api/v2/debates/{debate_id}                  - Update debate metadata
- DELETE /api/v2/debates/{debate_id}                  - Delete a debate

Migration Notes:
    This module replaces the CrudOperationsMixin in the legacy debates handler
    with native FastAPI routes. Key improvements:
    - Pydantic request/response models with automatic validation
    - FastAPI dependency injection for auth and storage
    - Proper HTTP status codes (422 for validation, 404 for not found)
    - OpenAPI schema auto-generation
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
import inspect
import json as json_mod
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

from aragora.agents.spec import AgentSpec
from aragora.rbac.models import AuthorizationContext
from aragora.tenancy.record_scope import OrgScope, require_org_scope_fastapi

from ..dependencies.auth import require_permission
from ..middleware.error_handling import NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", tags=["Debates"])

# =============================================================================
# Pydantic Models
# =============================================================================


class DebateSummary(BaseModel):
    """Summary of a debate for list views."""

    id: str
    task: str
    status: str
    created_at: str | None = None
    updated_at: str | None = None
    round_count: int = 0
    agent_count: int = 0
    has_consensus: bool = False

    model_config = {"extra": "allow"}


class DebateListResponse(BaseModel):
    """Response for debate listing."""

    debates: list[DebateSummary]
    total: int
    limit: int
    offset: int


class DebateDetail(BaseModel):
    """Full debate details."""

    id: str
    task: str
    status: str
    protocol: dict[str, Any] = Field(default_factory=dict)
    agents: list[str] = Field(default_factory=list)
    rounds: list[dict[str, Any]] = Field(default_factory=list)
    final_answer: str | None = None
    consensus: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class MessageResponse(BaseModel):
    """Response for debate messages."""

    debate_id: str
    messages: list[dict[str, Any]]
    total: int
    has_more: bool


class ConvergenceResponse(BaseModel):
    """Response for convergence status."""

    debate_id: str
    converged: bool
    confidence: float = 0.0
    rounds_to_convergence: int | None = None
    similarity_scores: list[float] = Field(default_factory=list)


class UpdateDebateRequest(BaseModel):
    """Request body for PATCH /debates/{debate_id}.

    All fields are optional. Only provided fields are updated.
    """

    title: str | None = Field(None, max_length=500, description="Update debate title")
    tags: list[str] | None = Field(None, max_length=50, description="Update tags")
    status: str | None = Field(
        None, description="Update status (active, paused, concluded, archived)"
    )
    metadata: dict[str, Any] | None = Field(None, description="Update custom metadata")


class UpdateDebateResponse(BaseModel):
    """Response for PATCH /debates/{debate_id}."""

    success: bool
    debate_id: str
    updated_fields: list[str]
    debate: DebateSummary


class DeleteDebateResponse(BaseModel):
    """Response for DELETE /debates/{debate_id}."""

    deleted: bool
    id: str


class CreateDebateRequest(BaseModel):
    """Request body for POST /debates.

    Mirrors the legacy /api/v1/debates POST body.
    """

    question: str = Field(
        ..., min_length=1, max_length=5000, description="Topic/question to debate"
    )
    agents: str | dict[str, Any] | list[str | dict[str, Any]] | None = Field(
        None,
        description="Agent specs as a comma-separated string, object, or list",
    )
    rounds: int = Field(3, ge=1, le=20, description="Number of debate rounds")
    consensus: str = Field("majority", description="Consensus method")
    auto_select: bool = Field(False, description="Auto-select agents")
    context: str | None = Field(None, max_length=10000, description="Additional context")
    metadata: dict[str, Any] | None = Field(None, description="Custom metadata")
    comparison_config: dict[str, Any] | None = Field(
        None,
        description="Run the same debate across candidate lineups and keep the best result",
    )
    model_comparison: dict[str, Any] | None = Field(
        None,
        description="Deprecated alias for comparison_config",
    )
    agent_combinations: list[Any] | None = Field(
        None,
        description="Deprecated alias for comparison_config.agent_combinations",
    )
    model_combinations: list[Any] | None = Field(
        None,
        description="Human-facing alias for comparison_config.agent_combinations",
    )

    @field_validator("agents")
    @classmethod
    def validate_agents(
        cls, value: str | dict[str, Any] | list[str | dict[str, Any]] | None
    ) -> str | dict[str, Any] | list[str | dict[str, Any]] | None:
        """Reject malformed structured agent specs early."""
        if value in (None, ""):
            return None
        if isinstance(value, str):
            return value
        try:
            AgentSpec.coerce_list(value, warn=False)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        return value


class CreateDebateResponse(BaseModel):
    """Response for POST /debates."""

    debate_id: str
    status: str
    message: str | None = None

    model_config = {"extra": "allow"}


class ExportResponse(BaseModel):
    """Response for debate export (JSON format)."""

    debate_id: str
    format: str
    content: Any


class ArgumentGraphResponse(BaseModel):
    """Response for argument graph."""

    debate_id: str
    format: str
    graph: Any


class GraphStatsResponse(BaseModel):
    """Response for graph statistics."""

    node_count: int = 0
    edge_count: int = 0
    depth: int = 0
    clusters: int = 0
    avg_branching_factor: float = 0.0
    avg_path_length: float = 0.0

    model_config = {"extra": "allow"}


# =============================================================================
# Dependencies
# =============================================================================


async def get_storage(request: Request):
    """Dependency to get storage from app state."""
    ctx = getattr(request.app.state, "context", None)
    if not ctx:
        raise HTTPException(status_code=503, detail="Server not initialized")

    storage = ctx.get("storage")
    if not storage:
        raise HTTPException(status_code=503, detail="Storage not available")

    return storage


async def _call_storage_method(storage: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
    """Run storage methods without blocking the FastAPI event loop."""

    method = getattr(storage, method_name)
    return await _call_sync_aware(method, *args, **kwargs)


async def _call_sync_aware(func: Any, *args: Any, **kwargs: Any) -> Any:
    """Run sync callables in a worker thread while awaiting async callables directly."""

    if inspect.iscoroutinefunction(func):
        return await func(*args, **kwargs)

    result = await asyncio.to_thread(func, *args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def get_nomic_dir() -> Path | None:
    """Get the nomic directory from environment."""
    nomic_dir_str = os.environ.get("ARAGORA_NOMIC_DIR", ".")
    nomic_dir = Path(nomic_dir_str)
    if nomic_dir.exists():
        return nomic_dir
    return None


def _lookup_value(record: Any, *names: str) -> Any:
    """Read a field from a dict- or object-backed record."""

    if isinstance(record, dict):
        for name in names:
            if name in record and record[name] is not None:
                return record[name]
        return None

    for name in names:
        value = getattr(record, name, None)
        if value is not None:
            return value
    return None


def _coerce_dict(value: Any) -> dict[str, Any]:
    """Convert common object containers into dictionaries for API responses."""

    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(exclude_none=True)
        if isinstance(dumped, dict):
            return dumped
    if hasattr(value, "to_dict"):
        dumped = value.to_dict()
        if isinstance(dumped, dict):
            return dumped
    if is_dataclass(value) and not isinstance(value, type):
        dumped = asdict(value)
        if isinstance(dumped, dict):
            return dumped
    if hasattr(value, "__dict__"):
        return {
            key: item
            for key, item in vars(value).items()
            if not key.startswith("_") and item is not None
        }
    return {}


def _coerce_message_list(messages: Any) -> list[dict[str, Any]]:
    """Normalize message payloads to dictionaries."""

    if not isinstance(messages, list):
        return []

    normalized: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, dict):
            normalized.append(message)
            continue

        message_dict = _coerce_dict(message)
        normalized.append(message_dict or {"content": str(message)})

    return normalized


def _extract_rounds(record: Any) -> list[dict[str, Any]]:
    """Normalize round payloads from dict- or object-backed debates."""

    rounds = _lookup_value(record, "rounds")
    if isinstance(rounds, list):
        normalized_rounds: list[dict[str, Any]] = []
        for index, round_data in enumerate(rounds, start=1):
            round_dict: dict[str, Any] = (
                dict(round_data) if isinstance(round_data, dict) else _coerce_dict(round_data)
            )
            if not round_dict:
                round_dict = {"round_num": index}
            round_dict["messages"] = _coerce_message_list(round_dict.get("messages", []))
            normalized_rounds.append(round_dict)
        return normalized_rounds

    messages = _lookup_value(record, "messages")
    if isinstance(messages, list) and messages:
        return [{"round_num": 1, "messages": _coerce_message_list(messages)}]

    return []


def _extract_agents(record: Any) -> list[str]:
    """Normalize agent identifiers from storage records."""

    agents = _lookup_value(record, "agents", "participants")
    if isinstance(agents, list):
        return [str(agent) for agent in agents]
    return []


def _extract_task(record: Any) -> str:
    """Resolve a debate task from common storage shapes."""

    task = _lookup_value(record, "task")
    if isinstance(task, str) and task.strip():
        return task

    environment = _coerce_dict(_lookup_value(record, "environment"))
    task = environment.get("task")
    return str(task) if task else ""


def _extract_consensus(record: Any) -> dict[str, Any] | None:
    """Normalize consensus details for popup polling and detail views."""

    raw_consensus = _lookup_value(record, "consensus", "consensus_proof")
    consensus = _coerce_dict(raw_consensus)

    confidence = _lookup_value(record, "confidence")
    if isinstance(confidence, (int, float)) and "confidence" not in consensus:
        consensus["confidence"] = float(confidence)

    reached = _lookup_value(record, "consensus_reached")
    if isinstance(reached, bool) and "reached" not in consensus:
        consensus["reached"] = reached

    final_answer = _lookup_value(record, "final_answer")
    if isinstance(final_answer, str) and final_answer and "final_answer" not in consensus:
        consensus["final_answer"] = final_answer

    if consensus:
        return consensus
    return None


def _extract_final_answer(record: Any, consensus: dict[str, Any] | None = None) -> str | None:
    """Resolve the best available final answer text."""

    final_answer = _lookup_value(record, "final_answer", "conclusion")
    if isinstance(final_answer, str) and final_answer.strip():
        return final_answer

    if consensus:
        for key in ("final_answer", "answer", "summary"):
            value = consensus.get(key)
            if isinstance(value, str) and value.strip():
                return value

    return None


def _extract_status(record: Any, consensus: dict[str, Any] | None, final_answer: str | None) -> str:
    """Resolve a stable status string for detail and list responses."""

    status = _lookup_value(record, "status")
    if isinstance(status, str) and status.strip():
        return status
    if consensus and consensus.get("reached") is True:
        return "completed"
    if final_answer:
        return "completed"
    return "unknown"


def _stringify_optional(value: Any) -> str | None:
    """Convert timestamps or IDs to strings without forcing empty values."""

    if value in (None, ""):
        return None
    return str(value)


def _auto_select_agents_for_fastapi(
    question: str,
    config: dict[str, Any],
    ctx: dict[str, Any],
) -> str:
    """Provide agent auto-selection for standalone FastAPI debate creation."""
    from aragora.server.agent_selection import auto_select_agents

    return auto_select_agents(
        question=question,
        config=config,
        elo_system=ctx.get("elo_system"),
        persona_manager=ctx.get("persona_manager"),
    )


def _build_fastapi_debate_controller(request: Request, storage: Any) -> Any:
    """Construct a debate controller directly from FastAPI app context."""
    from aragora.server.debate_controller import DebateController
    from aragora.server.debate_factory import DebateFactory
    from aragora.server.stream.emitter import SyncEventEmitter, get_global_emitter

    ctx = getattr(request.app.state, "context", {}) or {}
    emitter = ctx.get("stream_emitter") or get_global_emitter() or SyncEventEmitter()
    factory = DebateFactory(
        elo_system=ctx.get("elo_system"),
        persona_manager=ctx.get("persona_manager"),
        debate_embeddings=ctx.get("debate_embeddings"),
        position_tracker=ctx.get("position_tracker"),
        position_ledger=ctx.get("position_ledger"),
        flip_detector=ctx.get("flip_detector"),
        dissent_retriever=ctx.get("dissent_retriever"),
        moment_detector=ctx.get("moment_detector"),
        stream_emitter=emitter,
        document_store=ctx.get("document_store"),
        evidence_store=ctx.get("evidence_store"),
        knowledge_mound=ctx.get("knowledge_mound"),
    )

    return DebateController(
        factory=factory,
        emitter=emitter,
        elo_system=ctx.get("elo_system"),
        auto_select_fn=lambda question, config: _auto_select_agents_for_fastapi(
            question, config, ctx
        ),
        storage=storage,
    )


def _get_debate_controller(request: Request, storage: Any) -> Any:
    """Resolve a debate controller for FastAPI routes."""
    try:
        import aragora.server.debate_controller as debate_controller_mod  # type: ignore[import-not-found]
    except ImportError as e:
        logger.warning("Debate controller module not available: %s", e)
        raise HTTPException(status_code=503, detail="Debate orchestrator not available") from e

    try:
        controller_getter = getattr(debate_controller_mod, "get_debate_controller", None)
        if callable(controller_getter):
            controller = controller_getter()
            if controller is not None:
                return controller

        return _build_fastapi_debate_controller(request, storage)
    except HTTPException:
        raise
    except (RuntimeError, ValueError, TypeError, AttributeError, OSError) as e:
        logger.exception("Failed to resolve debate controller: %s", e)
        raise HTTPException(status_code=503, detail="Debate orchestrator not available") from e


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/debates", response_model=DebateListResponse)
async def list_debates(
    request: Request,
    limit: int = Query(50, ge=1, le=100, description="Max results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    status: str | None = Query(None, description="Filter by status"),
    storage=Depends(get_storage),
) -> DebateListResponse:
    """
    List all debates with pagination.

    Returns a paginated list of debate summaries.
    """
    try:
        # Get debates from storage
        if hasattr(storage, "list_debates"):
            debates_raw = await _call_storage_method(
                storage,
                "list_debates",
                limit=limit,
                offset=offset,
                status=status,
            )
        else:
            # Fallback for simpler storage implementations
            all_debates = list(storage.debates.values()) if hasattr(storage, "debates") else []
            debates_raw = all_debates[offset : offset + limit]

        # Get total count
        if hasattr(storage, "count_debates"):
            total = await _call_storage_method(storage, "count_debates", status=status)
        else:
            total = len(storage.debates) if hasattr(storage, "debates") else 0

        # Convert to summaries
        debates = []
        for d in debates_raw:
            consensus = _extract_consensus(d)
            final_answer = _extract_final_answer(d, consensus)
            summary = DebateSummary(
                id=str(_lookup_value(d, "id", "debate_id") or ""),
                task=_extract_task(d),
                status=_extract_status(d, consensus, final_answer),
                created_at=_stringify_optional(_lookup_value(d, "created_at")),
                updated_at=_stringify_optional(_lookup_value(d, "updated_at")),
                round_count=len(_extract_rounds(d)),
                agent_count=len(_extract_agents(d)),
                has_consensus=consensus is not None,
            )
            debates.append(summary)

        return DebateListResponse(
            debates=debates,
            total=total,
            limit=limit,
            offset=offset,
        )

    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error listing debates: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list debates")


@router.get("/debates/{debate_id}", response_model=DebateDetail)
async def get_debate(
    debate_id: str,
    storage=Depends(get_storage),
) -> DebateDetail:
    """
    Get debate by ID.

    Returns full debate details including rounds and consensus.
    """
    try:
        # Get debate from storage
        if hasattr(storage, "get_debate"):
            debate = await _call_storage_method(storage, "get_debate", debate_id)
        elif hasattr(storage, "debates"):
            debate = storage.debates.get(debate_id)
        else:
            debate = None

        if not debate:
            raise NotFoundError(f"Debate {debate_id} not found")

        consensus = _extract_consensus(debate)
        final_answer = _extract_final_answer(debate, consensus)

        return DebateDetail(
            id=str(_lookup_value(debate, "id", "debate_id") or debate_id),
            task=_extract_task(debate),
            status=_extract_status(debate, consensus, final_answer),
            protocol=_coerce_dict(_lookup_value(debate, "protocol")),
            agents=_extract_agents(debate),
            rounds=_extract_rounds(debate),
            final_answer=final_answer,
            consensus=consensus,
            created_at=_stringify_optional(_lookup_value(debate, "created_at")),
            updated_at=_stringify_optional(_lookup_value(debate, "updated_at")),
            metadata=_coerce_dict(_lookup_value(debate, "metadata")),
        )

    except NotFoundError:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error getting debate %s: %s", debate_id, e)
        raise HTTPException(status_code=500, detail="Failed to get debate")


@router.get("/debates/{debate_id}/messages", response_model=MessageResponse)
async def get_debate_messages(
    debate_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    storage=Depends(get_storage),
) -> MessageResponse:
    """
    Get messages from a debate.

    Returns paginated list of debate messages/rounds.
    """
    try:
        # Get debate
        if hasattr(storage, "get_debate"):
            debate = await _call_storage_method(storage, "get_debate", debate_id)
        elif hasattr(storage, "debates"):
            debate = storage.debates.get(debate_id)
        else:
            debate = None

        if not debate:
            raise NotFoundError(f"Debate {debate_id} not found")

        # Extract messages from rounds
        messages: list[dict[str, Any]] = []

        rounds = (
            debate.get("rounds", []) if isinstance(debate, dict) else getattr(debate, "rounds", [])
        )

        for round_data in rounds:
            if isinstance(round_data, dict):
                round_messages = round_data.get("messages", [])
            else:
                round_messages = getattr(round_data, "messages", [])

            for msg in round_messages:
                if isinstance(msg, dict):
                    messages.append(msg)
                else:
                    messages.append(
                        msg.__dict__ if hasattr(msg, "__dict__") else {"content": str(msg)}
                    )

        # Paginate
        total = len(messages)
        messages = messages[offset : offset + limit]

        return MessageResponse(
            debate_id=debate_id,
            messages=messages,
            total=total,
            has_more=(offset + limit) < total,
        )

    except NotFoundError:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error getting messages for debate %s: %s", debate_id, e)
        raise HTTPException(status_code=500, detail="Failed to get messages")


@router.get("/debates/{debate_id}/convergence", response_model=ConvergenceResponse)
async def get_debate_convergence(
    debate_id: str,
    storage=Depends(get_storage),
) -> ConvergenceResponse:
    """
    Get convergence status for a debate.

    Returns whether the debate has converged and related metrics.
    """
    try:
        # Get debate
        if hasattr(storage, "get_debate"):
            debate = await _call_storage_method(storage, "get_debate", debate_id)
        elif hasattr(storage, "debates"):
            debate = storage.debates.get(debate_id)
        else:
            debate = None

        if not debate:
            raise NotFoundError(f"Debate {debate_id} not found")

        consensus = _extract_consensus(debate)
        converged = consensus is not None and bool(
            consensus.get("reached", True) or consensus.get("final_answer")
        )
        confidence = float(consensus.get("confidence", 0.0)) if consensus else 0.0

        # Get similarity scores if available
        similarity_scores: list[float] = []
        if isinstance(debate, dict):
            metrics = debate.get("metrics", {})
            similarity_scores = metrics.get("similarity_scores", [])
        else:
            metrics = getattr(debate, "metrics", None)
            if metrics:
                similarity_scores = getattr(metrics, "similarity_scores", [])

        return ConvergenceResponse(
            debate_id=debate_id,
            converged=converged,
            confidence=confidence,
            rounds_to_convergence=len(_extract_rounds(debate)) if converged else None,
            similarity_scores=similarity_scores,
        )

    except NotFoundError:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error getting convergence for debate %s: %s", debate_id, e)
        raise HTTPException(status_code=500, detail="Failed to get convergence")


# Valid status values (internal + SDK)
_VALID_STATUSES = {
    "active",
    "paused",
    "concluded",
    "archived",  # internal
    "pending",
    "running",
    "completed",
    "failed",
    "cancelled",  # SDK
}


@router.patch("/debates/{debate_id}", response_model=UpdateDebateResponse)
async def update_debate(
    debate_id: str,
    body: UpdateDebateRequest,
    auth: AuthorizationContext = Depends(require_permission("debates:write")),
    storage=Depends(get_storage),
) -> UpdateDebateResponse:
    """
    Update debate metadata.

    Allows updating title, tags, status, and custom metadata.
    Requires `debates:write` permission.
    """
    try:
        # Get debate from storage
        if hasattr(storage, "get_debate"):
            debate = await _call_storage_method(storage, "get_debate", debate_id)
        elif hasattr(storage, "debates"):
            debate = storage.debates.get(debate_id)
        else:
            debate = None

        if not debate:
            raise NotFoundError(f"Debate {debate_id} not found")

        # Build updates from non-None fields
        updates: dict[str, Any] = {}
        if body.title is not None:
            updates["title"] = body.title
        if body.tags is not None:
            updates["tags"] = body.tags
        if body.status is not None:
            if body.status not in _VALID_STATUSES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid status. Must be one of: {', '.join(sorted(_VALID_STATUSES))}",
                )
            updates["status"] = body.status
        if body.metadata is not None:
            updates["metadata"] = body.metadata

        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        # Apply updates
        if isinstance(debate, dict):
            for key, value in updates.items():
                debate[key] = value
        else:
            for key, value in updates.items():
                setattr(debate, key, value)

        # Save updated debate
        if hasattr(storage, "save_debate"):
            await _call_storage_method(storage, "save_debate", debate_id, debate)

        logger.info("Debate %s updated: %s", debate_id, list(updates.keys()))

        # Build response
        if isinstance(debate, dict):
            summary = DebateSummary(
                id=debate.get("id", debate_id),
                task=debate.get("task", debate.get("title", "")),
                status=debate.get("status", "unknown"),
                created_at=debate.get("created_at"),
                updated_at=debate.get("updated_at"),
                round_count=len(debate.get("rounds", [])),
                agent_count=len(debate.get("agents", [])),
                has_consensus=debate.get("consensus") is not None,
            )
        else:
            summary = DebateSummary(
                id=getattr(debate, "id", debate_id),
                task=getattr(debate, "task", ""),
                status=getattr(debate, "status", "unknown"),
                round_count=len(getattr(debate, "rounds", [])),
                agent_count=len(getattr(debate, "agents", [])),
                has_consensus=getattr(debate, "consensus", None) is not None,
            )

        return UpdateDebateResponse(
            success=True,
            debate_id=debate_id,
            updated_fields=list(updates.keys()),
            debate=summary,
        )

    except NotFoundError:
        raise
    except HTTPException:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error updating debate %s: %s", debate_id, e)
        raise HTTPException(status_code=500, detail="Failed to update debate")


@router.delete("/debates/{debate_id}", response_model=DeleteDebateResponse)
async def delete_debate(
    debate_id: str,
    auth: AuthorizationContext = Depends(require_permission("debates:delete")),
    storage=Depends(get_storage),
) -> DeleteDebateResponse:
    """
    Delete a debate.

    Permanently deletes a debate and cascades to associated data.
    For soft-delete, use PATCH with status='archived' instead.
    Requires `debates:delete` permission.
    """
    try:
        # Check debate exists
        if hasattr(storage, "get_debate"):
            debate = await _call_storage_method(storage, "get_debate", debate_id)
        elif hasattr(storage, "debates"):
            debate = storage.debates.get(debate_id)
        else:
            debate = None

        if not debate:
            raise NotFoundError(f"Debate {debate_id} not found")

        # Perform deletion
        deleted = False
        if hasattr(storage, "delete_debate"):
            deleted = await _call_storage_method(
                storage,
                "delete_debate",
                debate_id,
                cascade_critiques=True,
            )
        elif hasattr(storage, "debates") and debate_id in storage.debates:
            del storage.debates[debate_id]
            deleted = True

        if not deleted:
            raise NotFoundError(f"Debate {debate_id} not found")

        logger.info("Debate %s permanently deleted", debate_id)
        return DeleteDebateResponse(deleted=True, id=debate_id)

    except NotFoundError:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error deleting debate %s: %s", debate_id, e)
        raise HTTPException(status_code=500, detail="Failed to delete debate")


# =============================================================================
# New Endpoints (Issue #258)
# =============================================================================


@router.post("/debates", response_model=CreateDebateResponse, status_code=200)
async def create_debate(
    body: CreateDebateRequest,
    request: Request,
    auth: AuthorizationContext = Depends(require_permission("debates:create")),
    scope: OrgScope = Depends(require_org_scope_fastapi),
    storage=Depends(get_storage),
) -> CreateDebateResponse:
    """
    Create a new debate owned by the caller's org.

    Validates the request and delegates to the debate controller for
    actual debate orchestration. Returns the debate_id for polling/streaming.
    Requires `debates:create` permission and an org (403 ``org_required``).
    """
    try:
        # Build debate body in legacy format for controller compatibility
        debate_body: dict[str, Any] = {
            "question": body.question,
            "rounds": body.rounds,
            "consensus": body.consensus,
            "auto_select": body.auto_select,
        }
        if body.agents:
            debate_body["agents"] = body.agents
        if body.context:
            debate_body["context"] = body.context
        if body.metadata:
            debate_body["metadata"] = body.metadata
        if body.comparison_config is not None:
            debate_body["comparison_config"] = body.comparison_config
        if body.model_comparison is not None:
            debate_body["model_comparison"] = body.model_comparison
        if body.agent_combinations is not None:
            debate_body["agent_combinations"] = body.agent_combinations
        if body.model_combinations is not None:
            debate_body["model_combinations"] = body.model_combinations

        # Delegate to the debate controller
        try:
            from aragora.server.debate_controller import DebateRequest

            debate_request = DebateRequest.from_dict(debate_body)
        except (ImportError, ValueError) as e:
            logger.warning("Invalid debate request: %s", e)
            raise HTTPException(status_code=400, detail="Invalid debate request")

        debate_request.org_id = scope.org_id
        debate_request.created_by = scope.user_id or None

        try:
            controller = _get_debate_controller(request, storage)
            response = await _call_sync_aware(controller.start_debate, debate_request)
        except (TypeError, ValueError, AttributeError, KeyError, RuntimeError, OSError) as e:
            logger.exception("Failed to start debate: %s", e)
            raise HTTPException(status_code=500, detail="Failed to start debate")

        if not getattr(response, "success", False):
            status_code = getattr(response, "status_code", 500)
            if not isinstance(status_code, int) or status_code < 400 or status_code > 599:
                status_code = 500

            detail = getattr(response, "error", None) or "Failed to start debate"
            logger.warning("Debate create rejected: %s", detail)
            raise HTTPException(status_code=status_code, detail=detail)

        logger.info("Debate created: %s", response.debate_id)

        # Return the response from the controller
        response_data = response.to_dict() if hasattr(response, "to_dict") else {}
        return CreateDebateResponse(
            debate_id=response_data.get("debate_id", response.debate_id),
            status=response_data.get("status", "started"),
            message=response_data.get("message"),
            **{
                k: v
                for k, v in response_data.items()
                if k not in ("debate_id", "status", "message")
            },
        )

    except HTTPException:
        raise
    except NotFoundError:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error creating debate: %s", e)
        raise HTTPException(status_code=500, detail="Failed to create debate")


_VALID_EXPORT_FORMATS = {"json", "csv", "html", "txt", "md"}


@router.get("/debates/{debate_id}/export/{export_format}")
async def export_debate(
    debate_id: str,
    export_format: str,
    table: str = Query("summary", description="Table type for CSV export"),
    auth: AuthorizationContext = Depends(require_permission("export:read")),
    storage=Depends(get_storage),
) -> Response:
    """
    Export a debate in the specified format.

    Supports JSON, CSV, HTML, TXT, and Markdown formats.
    Requires `export:read` permission.
    """
    if export_format not in _VALID_EXPORT_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid format: {export_format}. Valid: {', '.join(sorted(_VALID_EXPORT_FORMATS))}",
        )

    try:
        # Get debate from storage
        if hasattr(storage, "get_debate"):
            debate = await _call_storage_method(storage, "get_debate", debate_id)
        elif hasattr(storage, "debates"):
            debate = storage.debates.get(debate_id)
        else:
            debate = None

        if not debate:
            raise NotFoundError(f"Debate {debate_id} not found")

        # JSON export returns directly
        if export_format == "json":
            debate_data = (
                debate
                if isinstance(debate, dict)
                else (debate.__dict__ if hasattr(debate, "__dict__") else {})
            )
            return Response(
                content=json_mod.dumps(debate_data, indent=2, default=str),
                media_type="application/json",
                headers={"Content-Disposition": f'attachment; filename="debate_{debate_id}.json"'},
            )

        # Delegate to the export formatters for other formats
        try:
            from aragora.server.debate_export import (
                format_debate_csv,
                format_debate_html,
                format_debate_md,
                format_debate_txt,
            )
        except ImportError:
            raise HTTPException(status_code=503, detail="Export module not available")

        debate_dict = (
            debate
            if isinstance(debate, dict)
            else (debate.__dict__ if hasattr(debate, "__dict__") else {})
        )

        if export_format == "csv":
            result = format_debate_csv(debate_dict, table)
        elif export_format == "html":
            result = format_debate_html(debate_dict)
        elif export_format == "txt":
            result = format_debate_txt(debate_dict)
        elif export_format == "md":
            result = format_debate_md(debate_dict)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported format: {export_format}")

        raw_content: str | bytes = result.content  # type: ignore[assignment]
        content = raw_content.decode("utf-8") if isinstance(raw_content, bytes) else raw_content

        return Response(
            content=content,
            media_type=getattr(result, "content_type", "text/plain"),
            headers={
                "Content-Disposition": f'attachment; filename="{getattr(result, "filename", f"debate_{debate_id}.{export_format}")}"'
            },
        )

    except NotFoundError:
        raise
    except HTTPException:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error exporting debate %s: %s", debate_id, e)
        raise HTTPException(status_code=500, detail="Failed to export debate")


@router.get("/debates/{debate_id}/argument-graph", response_model=ArgumentGraphResponse)
async def get_argument_graph(
    debate_id: str,
    output_format: str = Query(
        "json", alias="format", description="Output format: json or mermaid"
    ),
    auth: AuthorizationContext = Depends(require_permission("analysis:read")),
) -> ArgumentGraphResponse:
    """
    Get the argument graph for a debate.

    Reconstructs the graph from stored debate traces via ArgumentCartographer.
    Supports JSON (default) and Mermaid diagram output.
    Requires `analysis:read` permission.
    """
    try:
        from aragora.debate.traces import DebateTrace
        from aragora.visualization.mapper import ArgumentCartographer
    except ImportError:
        raise HTTPException(status_code=503, detail="Graph analysis module not available")

    nomic_dir = get_nomic_dir()
    if not nomic_dir:
        raise HTTPException(status_code=503, detail="Nomic directory not configured")

    try:
        trace_path = nomic_dir / "traces" / f"{debate_id}.json"
        if not trace_path.exists():
            raise NotFoundError(f"Debate {debate_id} not found")

        trace = DebateTrace.load(trace_path)
        result = trace.to_debate_result()

        cartographer = ArgumentCartographer()
        cartographer.set_debate_context(debate_id, result.task or "")

        for msg in result.messages:
            cartographer.update_from_message(
                agent=msg.agent,
                content=msg.content,
                role=msg.role,
                round_num=msg.round,
            )

        for critique in result.critiques:
            cartographer.update_from_critique(
                critic_agent=critique.agent,
                target_agent=critique.target or "",
                severity=critique.severity,
                round_num=getattr(critique, "round", 1),
                critique_text=critique.reasoning,
            )

        if output_format == "mermaid":
            mermaid_code = cartographer.export_mermaid()
            return ArgumentGraphResponse(
                debate_id=debate_id,
                format="mermaid",
                graph=mermaid_code,
            )

        # Default: JSON graph
        graph_json = json_mod.loads(cartographer.export_json())
        return ArgumentGraphResponse(
            debate_id=debate_id,
            format="json",
            graph=graph_json,
        )

    except NotFoundError:
        raise
    except HTTPException:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error getting argument graph for debate %s: %s", debate_id, e)
        raise HTTPException(status_code=500, detail="Failed to get argument graph")


@router.get("/debates/{debate_id}/stats", response_model=GraphStatsResponse)
async def get_debate_stats(
    debate_id: str,
    auth: AuthorizationContext = Depends(require_permission("analysis:read")),
) -> GraphStatsResponse:
    """
    Get argument graph statistics for a debate.

    Returns node counts, edge counts, depth, branching factor, and complexity.
    Requires `analysis:read` permission.
    """
    try:
        from aragora.debate.traces import DebateTrace
        from aragora.visualization.mapper import ArgumentCartographer
    except ImportError:
        raise HTTPException(status_code=503, detail="Graph analysis module not available")

    nomic_dir = get_nomic_dir()
    if not nomic_dir:
        raise HTTPException(status_code=503, detail="Nomic directory not configured")

    try:
        trace_path = nomic_dir / "traces" / f"{debate_id}.json"

        if not trace_path.exists():
            # Try replays directory as fallback
            replay_path = nomic_dir / "replays" / debate_id / "events.jsonl"
            if replay_path.exists():
                return await _build_stats_from_replay(debate_id, replay_path)
            raise NotFoundError(f"Debate {debate_id} not found")

        # Load from trace file
        trace = DebateTrace.load(trace_path)
        result = trace.to_debate_result()

        # Build cartographer from debate result
        cartographer = ArgumentCartographer()
        cartographer.set_debate_context(debate_id, result.task or "")

        for msg in result.messages:
            cartographer.update_from_message(
                agent=msg.agent,
                content=msg.content,
                role=msg.role,
                round_num=msg.round,
            )

        for critique in result.critiques:
            cartographer.update_from_critique(
                critic_agent=critique.agent,
                target_agent=critique.target or "",
                severity=critique.severity,
                round_num=getattr(critique, "round", 1),
                critique_text=critique.reasoning,
            )

        stats = cartographer.get_statistics()
        return GraphStatsResponse(**stats)

    except NotFoundError:
        raise
    except HTTPException:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error getting stats for debate %s: %s", debate_id, e)
        raise HTTPException(status_code=500, detail="Failed to get debate stats")


async def _build_stats_from_replay(debate_id: str, replay_path: Path) -> GraphStatsResponse:
    """Build graph stats from replay events file."""
    try:
        from aragora.visualization.mapper import ArgumentCartographer
    except ImportError:
        raise HTTPException(status_code=503, detail="Graph analysis module not available")

    try:
        cartographer = ArgumentCartographer()
        cartographer.set_debate_context(debate_id, "")

        with replay_path.open() as f:
            for line_num, line in enumerate(f, 1):
                if line.strip():
                    try:
                        event = json_mod.loads(line)
                    except json_mod.JSONDecodeError:
                        logger.warning("Skipping malformed JSONL line %s", line_num)
                        continue

                    if event.get("type") == "agent_message":
                        cartographer.update_from_message(
                            agent=event.get("agent", "unknown"),
                            content=event.get("data", {}).get("content", ""),
                            role=event.get("data", {}).get("role", "proposer"),
                            round_num=event.get("round", 1),
                        )
                    elif event.get("type") == "critique":
                        cartographer.update_from_critique(
                            critic_agent=event.get("agent", "unknown"),
                            target_agent=event.get("data", {}).get("target", "unknown"),
                            severity=event.get("data", {}).get("severity", 0.5),
                            round_num=event.get("round", 1),
                            critique_text=event.get("data", {}).get("content", ""),
                        )

        stats = cartographer.get_statistics()
        return GraphStatsResponse(**stats)

    except FileNotFoundError:
        raise NotFoundError(f"Replay file not found: {debate_id}")
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error building stats from replay %s: %s", debate_id, e)
        raise HTTPException(status_code=500, detail="Failed to build stats from replay")
