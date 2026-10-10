"""
Knowledge Base Endpoints (FastAPI v2).

Migrated from: aragora/server/handlers/knowledge_base/ (legacy handler)

Provides the fact-oriented knowledge base API:
- GET    /api/v2/knowledge-base/facts             - List facts with filtering
- GET    /api/v2/knowledge-base/facts/{fact_id}    - Get a specific fact
- POST   /api/v2/knowledge-base/facts              - Create a new fact
- PUT    /api/v2/knowledge-base/facts/{fact_id}    - Update an existing fact
- DELETE /api/v2/knowledge-base/facts/{fact_id}    - Delete a fact
- POST   /api/v2/knowledge-base/facts/{fact_id}/verify         - Verify fact with agents
- GET    /api/v2/knowledge-base/facts/{fact_id}/contradictions  - Get contradicting facts
- GET    /api/v2/knowledge-base/facts/{fact_id}/relations       - Get fact relations
- POST   /api/v2/knowledge-base/facts/{fact_id}/relations       - Add relation from fact
- POST   /api/v2/knowledge-base/facts/relations    - Add relation between two facts
- POST   /api/v2/knowledge-base/query              - Natural language query
- GET    /api/v2/knowledge-base/search             - Search chunks via embeddings
- GET    /api/v2/knowledge-base/stats              - Knowledge base statistics
- GET    /api/v2/knowledge-base/export             - Export knowledge base
- POST   /api/v2/knowledge-base/import             - Import knowledge entries
- GET    /api/v2/knowledge-base/sync-status        - Sync status

Migration Notes:
    This module replaces the legacy KnowledgeHandler (which combined
    FactsOperationsMixin, QueryOperationsMixin, and SearchOperationsMixin)
    with native FastAPI routes. Key improvements:
    - Pydantic request/response models with automatic validation
    - FastAPI dependency injection for auth and storage
    - Proper HTTP status codes (422 for validation, 404 for not found)
    - OpenAPI schema auto-generation

    Note: The existing ``knowledge.py`` routes cover the Knowledge Mound
    (higher-level knowledge items, adapters, gap detection). This module
    covers the lower-level FactStore API (facts, relations, queries, search).

Organization scoping:
    POST /facts and POST /import bind each new fact to the caller's
    organization; a caller without one gets 403 ``knowledge_org_required``.
    Until organization scoping lands for the other fact routes, every route
    that reads or changes stored facts (everything except POST /facts,
    POST /import and GET /sync-status) answers 401 to anonymous callers and
    403 ``knowledge_fact_access_closed`` to every authenticated caller.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from aragora.rbac.models import AuthorizationContext

from ..dependencies.auth import require_authenticated, require_permission
from ..middleware.error_handling import APIError, NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/knowledge-base", tags=["Knowledge Base"])

_WORKSPACE_ID_MAX_LENGTH = 100


# =============================================================================
# Graceful subsystem imports
# =============================================================================

try:
    from aragora.knowledge import (
        DatasetQueryEngine,
        FactFilters,
        FactRelationType,
        FactStore,
        InMemoryEmbeddingService,
        InMemoryFactStore,
        QueryOptions,
        SimpleQueryEngine,
        ValidationStatus,
    )

    _KNOWLEDGE_AVAILABLE = True
except ImportError:
    _KNOWLEDGE_AVAILABLE = False
    # Define stubs so the module still loads and reports 503 at runtime.
    DatasetQueryEngine = None  # type: ignore[assignment,misc]
    FactFilters = None  # type: ignore[assignment,misc]
    FactRelationType = None  # type: ignore[assignment,misc]
    FactStore = None  # type: ignore[assignment,misc]
    InMemoryEmbeddingService = None  # type: ignore[assignment,misc]
    InMemoryFactStore = None  # type: ignore[assignment,misc]
    QueryOptions = None  # type: ignore[assignment,misc]
    SimpleQueryEngine = None  # type: ignore[assignment,misc]
    ValidationStatus = None  # type: ignore[assignment,misc]
    logger.info("aragora.knowledge not available; knowledge-base routes will return 503")


# =============================================================================
# Pydantic Models
# =============================================================================


class FactSummary(BaseModel):
    """Summary representation of a fact."""

    id: str
    statement: str = ""
    confidence: float = 0.0
    topics: list[str] = Field(default_factory=list)
    workspace_id: str = "default"
    validation_status: str = "unverified"
    created_at: str | None = None
    updated_at: str | None = None

    model_config = {"extra": "allow"}


class FactDetail(BaseModel):
    """Full fact details including evidence and metadata."""

    id: str
    statement: str = ""
    confidence: float = 0.0
    topics: list[str] = Field(default_factory=list)
    workspace_id: str = "default"
    validation_status: str = "unverified"
    evidence_ids: list[str] = Field(default_factory=list)
    source_documents: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    superseded_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    model_config = {"extra": "allow"}


class FactListResponse(BaseModel):
    """Response for GET /facts."""

    facts: list[FactSummary]
    total: int
    limit: int
    offset: int


class CreateFactRequest(BaseModel):
    """Request body for POST /facts."""

    statement: str = Field(..., min_length=1, max_length=5000, description="The fact statement")
    workspace_id: str = Field("default", max_length=100, description="Workspace ID")
    evidence_ids: list[str] = Field(default_factory=list, description="Evidence IDs")
    source_documents: list[str] = Field(default_factory=list, description="Source document refs")
    confidence: float = Field(0.5, ge=0.0, le=1.0, description="Confidence score")
    topics: list[str] = Field(default_factory=list, description="Topic tags")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class UpdateFactRequest(BaseModel):
    """Request body for PUT /facts/{fact_id}."""

    confidence: float | None = Field(None, ge=0.0, le=1.0, description="Updated confidence")
    validation_status: str | None = Field(None, description="Updated validation status")
    evidence_ids: list[str] | None = Field(None, description="Updated evidence IDs")
    topics: list[str] | None = Field(None, description="Updated topics")
    metadata: dict[str, Any] | None = Field(None, description="Updated metadata")
    superseded_by: str | None = Field(None, description="ID of superseding fact")


class FactRelation(BaseModel):
    """A relation between two facts."""

    relation_type: str
    source_fact_id: str
    target_fact_id: str
    confidence: float = 0.5
    created_by: str = ""
    metadata: dict[str, Any] | None = None

    model_config = {"extra": "allow"}


class FactRelationsResponse(BaseModel):
    """Response for GET /facts/{fact_id}/relations."""

    fact_id: str
    relations: list[FactRelation]
    count: int


class AddRelationRequest(BaseModel):
    """Request body for POST /facts/{fact_id}/relations."""

    target_fact_id: str = Field(..., description="Target fact ID")
    relation_type: str = Field(..., description="Relation type")
    confidence: float = Field(0.5, ge=0.0, le=1.0, description="Confidence")
    created_by: str = Field("", description="Creator identifier")
    metadata: dict[str, Any] | None = Field(None, description="Extra metadata")


class AddRelationBulkRequest(BaseModel):
    """Request body for POST /facts/relations (bulk endpoint)."""

    source_fact_id: str = Field(..., description="Source fact ID")
    target_fact_id: str = Field(..., description="Target fact ID")
    relation_type: str = Field(..., description="Relation type")
    confidence: float = Field(0.5, ge=0.0, le=1.0, description="Confidence")
    created_by: str = Field("", description="Creator identifier")
    metadata: dict[str, Any] | None = Field(None, description="Extra metadata")


class ContradictionsResponse(BaseModel):
    """Response for GET /facts/{fact_id}/contradictions."""

    fact_id: str
    contradictions: list[FactSummary]
    count: int


class VerifyFactResponse(BaseModel):
    """Response for POST /facts/{fact_id}/verify."""

    fact_id: str
    verified: bool | None = None
    status: str = "completed"
    message: str = ""

    model_config = {"extra": "allow"}


class QueryRequest(BaseModel):
    """Request body for POST /query."""

    question: str = Field(
        ..., min_length=1, max_length=5000, description="Natural language question"
    )
    workspace_id: str = Field("default", max_length=100, description="Workspace ID")
    options: dict[str, Any] = Field(
        default_factory=dict,
        description="Query options: max_chunks, search_alpha, use_agents, etc.",
    )


class QueryResponse(BaseModel):
    """Response for POST /query."""

    answer: str = ""
    confidence: float = 0.0
    citations: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class SearchResponse(BaseModel):
    """Response for GET /search."""

    query: str
    workspace_id: str
    results: list[dict[str, Any]]
    count: int


class StatsResponse(BaseModel):
    """Response for GET /stats."""

    workspace_id: str | None = None
    total_facts: int = 0
    total_relations: int = 0
    topics: list[str] = Field(default_factory=list)
    by_status: dict[str, int] = Field(default_factory=dict)
    by_workspace: dict[str, int] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class ExportResponse(BaseModel):
    """Response for GET /export."""

    format: str = "json"
    facts: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    exported_at: str = ""


class ImportRequest(BaseModel):
    """Request body for POST /import."""

    facts: list[dict[str, Any]] = Field(..., description="List of fact dicts to import")
    workspace_id: str = Field(
        "default", max_length=_WORKSPACE_ID_MAX_LENGTH, description="Target workspace"
    )
    merge_strategy: Literal["skip_existing"] = Field(
        "skip_existing",
        description=(
            "How to handle an entry that is already stored: only skip_existing is "
            "supported (the entry is counted in skipped)"
        ),
    )

    @field_validator("facts")
    @classmethod
    def _entry_workspace_is_a_short_string(
        cls, facts: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        for index, fact in enumerate(facts):
            if "workspace_id" not in fact:
                continue
            workspace_id = fact["workspace_id"]
            if not isinstance(workspace_id, str) or len(workspace_id) > _WORKSPACE_ID_MAX_LENGTH:
                raise ValueError(
                    f"facts[{index}].workspace_id must be a string of at most "
                    f"{_WORKSPACE_ID_MAX_LENGTH} characters"
                )
        return facts


class ImportResponse(BaseModel):
    """Response for POST /import."""

    imported: int = 0
    skipped: int = 0
    errors: int = 0
    total: int = 0
    details: list[str] = Field(default_factory=list)


class SyncStatusResponse(BaseModel):
    """Response for GET /sync-status."""

    synced: bool = True
    last_sync_at: str | None = None
    pending_changes: int = 0
    status: str = "ok"


# =============================================================================
# Dependencies
# =============================================================================


def _require_knowledge() -> None:
    """Raise 503 if the knowledge subsystem is not available."""
    if not _KNOWLEDGE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Knowledge subsystem not available")


FACT_ACCESS_CLOSED_MESSAGE = "Knowledge fact access is disabled until org scoping is available"
FACT_ACCESS_CLOSED_CODE = "knowledge_fact_access_closed"


async def _fact_access_closed(
    auth: AuthorizationContext = Depends(require_authenticated),
) -> None:
    """Answer 403 to every authenticated caller of a route that touches stored facts.

    Organization scoping has not landed for these routes yet, so none of them
    may touch stored facts. Route-level dependencies run before the
    route's own parameters are resolved, so this answers before the route's
    permission check and before the fact store or query engine is created;
    anonymous callers still get 401 from ``require_authenticated``.
    """
    raise APIError(FACT_ACCESS_CLOSED_MESSAGE, status_code=403, code=FACT_ACCESS_CLOSED_CODE)


_CLOSED_UNTIL_ORG_SCOPING = [Depends(_fact_access_closed)]


_fact_store_instance: Any = None
_query_engine_instance: Any = None


async def get_fact_store(request: Request) -> Any:
    """Dependency to get or create a FactStore."""
    global _fact_store_instance  # noqa: PLW0603
    _require_knowledge()

    # Try app-level context first
    ctx = getattr(request.app.state, "context", None)
    if ctx:
        store = ctx.get("fact_store")
        if store is not None:
            return store

    if _fact_store_instance is not None:
        return _fact_store_instance

    try:
        _fact_store_instance = FactStore()
    except (OSError, ValueError, TypeError, RuntimeError, ImportError) as e:
        logger.warning("Failed to create FactStore, using in-memory: %s", e)
        _fact_store_instance = InMemoryFactStore()

    return _fact_store_instance


async def get_query_engine(
    request: Request,
    store: Any = Depends(get_fact_store),
) -> Any:
    """Dependency to get or create a query engine."""
    global _query_engine_instance  # noqa: PLW0603
    _require_knowledge()

    ctx = getattr(request.app.state, "context", None)
    if ctx:
        engine = ctx.get("query_engine")
        if engine is not None:
            return engine

    if _query_engine_instance is not None:
        return _query_engine_instance

    embedding_service = InMemoryEmbeddingService()
    _query_engine_instance = SimpleQueryEngine(
        fact_store=store,
        embedding_service=embedding_service,
    )
    return _query_engine_instance


# =============================================================================
# Helpers
# =============================================================================


def _fact_to_summary(fact: Any) -> FactSummary:
    """Convert a fact object to a FactSummary Pydantic model."""
    if isinstance(fact, dict):
        return FactSummary(**fact)
    d = fact.to_dict() if hasattr(fact, "to_dict") else {}
    return FactSummary(
        id=d.get("id", getattr(fact, "id", "")),
        statement=d.get("statement", getattr(fact, "statement", "")),
        confidence=d.get("confidence", getattr(fact, "confidence", 0.0)),
        topics=d.get("topics", getattr(fact, "topics", [])),
        workspace_id=d.get("workspace_id", getattr(fact, "workspace_id", "default")),
        validation_status=d.get(
            "validation_status",
            str(getattr(fact, "validation_status", "unverified")),
        ),
        created_at=d.get("created_at", str(getattr(fact, "created_at", ""))),
        updated_at=d.get("updated_at", str(getattr(fact, "updated_at", ""))),
    )


def _fact_to_detail(fact: Any) -> FactDetail:
    """Convert a fact object to a FactDetail Pydantic model."""
    if isinstance(fact, dict):
        return FactDetail(**fact)
    d = fact.to_dict() if hasattr(fact, "to_dict") else {}
    return FactDetail(
        id=d.get("id", getattr(fact, "id", "")),
        statement=d.get("statement", getattr(fact, "statement", "")),
        confidence=d.get("confidence", getattr(fact, "confidence", 0.0)),
        topics=d.get("topics", getattr(fact, "topics", [])),
        workspace_id=d.get("workspace_id", getattr(fact, "workspace_id", "default")),
        validation_status=d.get(
            "validation_status",
            str(getattr(fact, "validation_status", "unverified")),
        ),
        evidence_ids=d.get("evidence_ids", getattr(fact, "evidence_ids", [])),
        source_documents=d.get("source_documents", getattr(fact, "source_documents", [])),
        metadata=d.get("metadata", getattr(fact, "metadata", {})),
        superseded_by=d.get("superseded_by", getattr(fact, "superseded_by", None)),
        created_at=d.get("created_at", str(getattr(fact, "created_at", ""))),
        updated_at=d.get("updated_at", str(getattr(fact, "updated_at", ""))),
    )


def _relation_to_model(relation: Any) -> FactRelation:
    """Convert a relation object to a FactRelation Pydantic model."""
    if isinstance(relation, dict):
        return FactRelation(**relation)
    d = relation.to_dict() if hasattr(relation, "to_dict") else {}
    return FactRelation(
        relation_type=d.get(
            "relation_type",
            str(getattr(relation, "relation_type", "")),
        ),
        source_fact_id=d.get("source_fact_id", getattr(relation, "source_fact_id", "")),
        target_fact_id=d.get("target_fact_id", getattr(relation, "target_fact_id", "")),
        confidence=d.get("confidence", getattr(relation, "confidence", 0.5)),
        created_by=d.get("created_by", getattr(relation, "created_by", "")),
        metadata=d.get("metadata", getattr(relation, "metadata", None)),
    )


async def _await_if_needed(result: Any) -> Any:
    """Await async engine results while tolerating sync test doubles."""
    if inspect.isawaitable(result):
        return await result
    return result


async def _call_store(store: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
    """Run FactStore methods without blocking the FastAPI event loop."""
    method = getattr(store, method_name)
    if inspect.iscoroutinefunction(method):
        return await method(*args, **kwargs)
    result = await asyncio.to_thread(method, *args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def _caller_org(auth: AuthorizationContext, action: str = "Creating knowledge facts") -> str:
    """The organization fact writes and chunk reads bind to: only the verified auth context."""
    if not auth.org_id:
        raise APIError(
            f"{action} requires an organization",
            status_code=403,
            code="knowledge_org_required",
        )
    return auth.org_id


# =============================================================================
# Fact CRUD Endpoints
# =============================================================================


@router.get("/facts", response_model=FactListResponse, dependencies=_CLOSED_UNTIL_ORG_SCOPING)
async def list_facts(
    request: Request,
    workspace_id: str | None = Query(None, max_length=100, description="Filter by workspace"),
    topic: str | None = Query(None, max_length=200, description="Filter by topic"),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0, description="Min confidence threshold"),
    status: str | None = Query(None, max_length=50, description="Filter by validation status"),
    include_superseded: bool = Query(False, description="Include superseded facts"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    offset: int = Query(0, ge=0, le=10000, description="Pagination offset"),
    auth: AuthorizationContext = Depends(require_authenticated),
    store: Any = Depends(get_fact_store),
) -> FactListResponse:
    """
    List facts with filtering and pagination.

    Returns facts from the knowledge base matching the specified filters.
    Supports filtering by workspace, topic, confidence, and validation status.
    """
    try:
        filters = FactFilters(
            workspace_id=workspace_id,
            topics=[topic] if topic else None,
            min_confidence=min_confidence,
            validation_status=ValidationStatus(status) if status else None,
            include_superseded=include_superseded,
            limit=limit,
            offset=offset,
        )

        facts = await _call_store(store, "list_facts", filters)
        summaries = [_fact_to_summary(f) for f in facts]

        return FactListResponse(
            facts=summaries,
            total=len(summaries),
            limit=limit,
            offset=offset,
        )

    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error listing facts: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list facts")


@router.get("/facts/{fact_id}", response_model=FactDetail, dependencies=_CLOSED_UNTIL_ORG_SCOPING)
async def get_fact(
    fact_id: str,
    auth: AuthorizationContext = Depends(require_authenticated),
    store: Any = Depends(get_fact_store),
) -> FactDetail:
    """
    Get a specific fact by ID.

    Returns the full details of a fact including evidence and metadata.
    """
    try:
        fact = await _call_store(store, "get_fact", fact_id)
        if not fact:
            raise NotFoundError(f"Fact not found: {fact_id}")
        return _fact_to_detail(fact)
    except NotFoundError:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error getting fact %s: %s", fact_id, e)
        raise HTTPException(status_code=500, detail="Failed to get fact")


@router.post("/facts", response_model=FactDetail, status_code=201)
async def create_fact(
    body: CreateFactRequest,
    auth: AuthorizationContext = Depends(require_permission("knowledge:write")),
    store: Any = Depends(get_fact_store),
) -> FactDetail:
    """
    Create a new fact.

    Adds a fact to the knowledge base with the given statement, confidence,
    topics, and metadata. Requires ``knowledge:write`` permission.
    """
    org_id = _caller_org(auth)
    try:
        fact = await _call_store(
            store,
            "add_fact",
            statement=body.statement,
            workspace_id=body.workspace_id,
            evidence_ids=body.evidence_ids,
            source_documents=body.source_documents,
            confidence=body.confidence,
            topics=body.topics,
            metadata=body.metadata,
            org_id=org_id,
        )
        return _fact_to_detail(fact)
    except HTTPException:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error creating fact: %s", e)
        raise HTTPException(status_code=500, detail="Failed to create fact")


@router.put("/facts/{fact_id}", response_model=FactDetail, dependencies=_CLOSED_UNTIL_ORG_SCOPING)
async def update_fact(
    fact_id: str,
    body: UpdateFactRequest,
    auth: AuthorizationContext = Depends(require_permission("knowledge:write")),
    store: Any = Depends(get_fact_store),
) -> FactDetail:
    """
    Update an existing fact.

    Partially updates the specified fields of a fact.
    Requires ``knowledge:write`` permission.
    """
    try:
        kwargs: dict[str, Any] = {}
        if body.confidence is not None:
            kwargs["confidence"] = body.confidence
        if body.validation_status is not None:
            kwargs["validation_status"] = ValidationStatus(body.validation_status)
        if body.evidence_ids is not None:
            kwargs["evidence_ids"] = body.evidence_ids
        if body.topics is not None:
            kwargs["topics"] = body.topics
        if body.metadata is not None:
            kwargs["metadata"] = body.metadata
        if body.superseded_by is not None:
            kwargs["superseded_by"] = body.superseded_by

        updated = await _call_store(store, "update_fact", fact_id, **kwargs)
        if not updated:
            raise NotFoundError(f"Fact not found: {fact_id}")

        return _fact_to_detail(updated)
    except NotFoundError:
        raise
    except HTTPException:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error updating fact %s: %s", fact_id, e)
        raise HTTPException(status_code=500, detail="Failed to update fact")


@router.delete("/facts/{fact_id}", dependencies=_CLOSED_UNTIL_ORG_SCOPING)
async def delete_fact(
    fact_id: str,
    auth: AuthorizationContext = Depends(require_permission("knowledge:delete")),
    store: Any = Depends(get_fact_store),
) -> dict[str, Any]:
    """
    Delete a fact.

    Permanently removes a fact from the knowledge base.
    Requires ``knowledge:delete`` permission.
    """
    try:
        deleted = await _call_store(store, "delete_fact", fact_id)
        if not deleted:
            raise NotFoundError(f"Fact not found: {fact_id}")
        return {"deleted": True, "fact_id": fact_id}
    except NotFoundError:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error deleting fact %s: %s", fact_id, e)
        raise HTTPException(status_code=500, detail="Failed to delete fact")


# =============================================================================
# Verify / Contradictions / Relations
# =============================================================================


@router.post(
    "/facts/{fact_id}/verify",
    response_model=VerifyFactResponse,
    dependencies=_CLOSED_UNTIL_ORG_SCOPING,
)
async def verify_fact(
    fact_id: str,
    auth: AuthorizationContext = Depends(require_permission("knowledge:write")),
    store: Any = Depends(get_fact_store),
    engine: Any = Depends(get_query_engine),
) -> VerifyFactResponse:
    """
    Verify a fact using AI agents.

    Submits the fact for agent-based verification. If the full
    DatasetQueryEngine is not available, the fact is queued for later
    verification.

    Requires ``knowledge:write`` permission.
    """
    try:
        fact = await _call_store(store, "get_fact", fact_id)
        if not fact:
            raise NotFoundError(f"Fact not found: {fact_id}")

        if DatasetQueryEngine is None or not isinstance(engine, DatasetQueryEngine):
            # Queue for later verification
            await _call_store(
                store,
                "update_fact",
                fact_id,
                metadata={
                    **(fact.metadata if hasattr(fact, "metadata") else {}),
                    "_pending_verification": True,
                    "_verification_queued_at": time.time(),
                },
            )
            return VerifyFactResponse(
                fact_id=fact_id,
                verified=None,
                status="queued",
                message=(
                    "Agent verification not currently available. "
                    "Fact queued for verification when capability becomes available."
                ),
            )

        try:
            verified = await _await_if_needed(engine.verify_fact(fact_id))
        except (KeyError, ValueError, OSError, TypeError, RuntimeError) as e:
            logger.error("Verification failed: %s", e)
            raise HTTPException(status_code=500, detail="Verification failed")

        result_dict = verified.to_dict() if hasattr(verified, "to_dict") else {}
        return VerifyFactResponse(
            fact_id=fact_id,
            verified=result_dict.get("verified"),
            status="completed",
            message=result_dict.get("message", ""),
            **{
                k: v
                for k, v in result_dict.items()
                if k not in ("fact_id", "verified", "status", "message")
            },
        )

    except NotFoundError:
        raise
    except HTTPException:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error verifying fact %s: %s", fact_id, e)
        raise HTTPException(status_code=500, detail="Failed to verify fact")


@router.get(
    "/facts/{fact_id}/contradictions",
    response_model=ContradictionsResponse,
    dependencies=_CLOSED_UNTIL_ORG_SCOPING,
)
async def get_contradictions(
    fact_id: str,
    auth: AuthorizationContext = Depends(require_authenticated),
    store: Any = Depends(get_fact_store),
) -> ContradictionsResponse:
    """
    Get facts that contradict a given fact.

    Returns a list of facts in the knowledge base that are identified as
    contradicting the specified fact.
    """
    try:
        fact = await _call_store(store, "get_fact", fact_id)
        if not fact:
            raise NotFoundError(f"Fact not found: {fact_id}")

        contradictions = await _call_store(store, "get_contradictions", fact_id)
        return ContradictionsResponse(
            fact_id=fact_id,
            contradictions=[_fact_to_summary(c) for c in contradictions],
            count=len(contradictions),
        )
    except NotFoundError:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error getting contradictions for %s: %s", fact_id, e)
        raise HTTPException(status_code=500, detail="Failed to get contradictions")


@router.get(
    "/facts/{fact_id}/relations",
    response_model=FactRelationsResponse,
    dependencies=_CLOSED_UNTIL_ORG_SCOPING,
)
async def get_relations(
    fact_id: str,
    relation_type: str | None = Query(
        None, alias="type", max_length=50, description="Filter by type"
    ),
    as_source: bool = Query(True, description="Include relations where fact is source"),
    as_target: bool = Query(True, description="Include relations where fact is target"),
    auth: AuthorizationContext = Depends(require_authenticated),
    store: Any = Depends(get_fact_store),
) -> FactRelationsResponse:
    """
    Get relations for a given fact.

    Returns relations where this fact is a source and/or target,
    optionally filtered by relation type.
    """
    try:
        fact = await _call_store(store, "get_fact", fact_id)
        if not fact:
            raise NotFoundError(f"Fact not found: {fact_id}")

        rel_type = FactRelationType(relation_type) if relation_type else None
        relations = await _call_store(
            store,
            "get_relations",
            fact_id,
            relation_type=rel_type,
            as_source=as_source,
            as_target=as_target,
        )

        return FactRelationsResponse(
            fact_id=fact_id,
            relations=[_relation_to_model(r) for r in relations],
            count=len(relations),
        )
    except NotFoundError:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error getting relations for %s: %s", fact_id, e)
        raise HTTPException(status_code=500, detail="Failed to get relations")


@router.post(
    "/facts/{fact_id}/relations",
    response_model=FactRelation,
    status_code=201,
    dependencies=_CLOSED_UNTIL_ORG_SCOPING,
)
async def add_relation(
    fact_id: str,
    body: AddRelationRequest,
    auth: AuthorizationContext = Depends(require_permission("knowledge:write")),
    store: Any = Depends(get_fact_store),
) -> FactRelation:
    """
    Add a relation from a specific fact to another.

    Creates a directional relation from the path-specified fact to the
    target fact specified in the request body.

    Requires ``knowledge:write`` permission.
    """
    try:
        rel_type = FactRelationType(body.relation_type)
    except (ValueError, KeyError):
        raise HTTPException(status_code=400, detail=f"Invalid relation_type: {body.relation_type}")

    try:
        if not await _call_store(store, "get_fact", fact_id):
            raise NotFoundError(f"Source fact not found: {fact_id}")
        if not await _call_store(store, "get_fact", body.target_fact_id):
            raise NotFoundError(f"Target fact not found: {body.target_fact_id}")

        relation = await _call_store(
            store,
            "add_relation",
            source_fact_id=fact_id,
            target_fact_id=body.target_fact_id,
            relation_type=rel_type,
            confidence=body.confidence,
            created_by=body.created_by,
            metadata=body.metadata,
        )
        return _relation_to_model(relation)
    except NotFoundError:
        raise
    except HTTPException:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error adding relation from %s: %s", fact_id, e)
        raise HTTPException(status_code=500, detail="Failed to add relation")


@router.post(
    "/facts/relations",
    response_model=FactRelation,
    status_code=201,
    dependencies=_CLOSED_UNTIL_ORG_SCOPING,
)
async def add_relation_bulk(
    body: AddRelationBulkRequest,
    auth: AuthorizationContext = Depends(require_permission("knowledge:write")),
    store: Any = Depends(get_fact_store),
) -> FactRelation:
    """
    Add a relation between two facts (bulk endpoint).

    Both source and target fact IDs are specified in the request body.
    Requires ``knowledge:write`` permission.
    """
    try:
        rel_type = FactRelationType(body.relation_type)
    except (ValueError, KeyError):
        raise HTTPException(status_code=400, detail=f"Invalid relation_type: {body.relation_type}")

    try:
        relation = await _call_store(
            store,
            "add_relation",
            source_fact_id=body.source_fact_id,
            target_fact_id=body.target_fact_id,
            relation_type=rel_type,
            confidence=body.confidence,
            created_by=body.created_by,
            metadata=body.metadata,
        )
        return _relation_to_model(relation)
    except HTTPException:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error adding bulk relation: %s", e)
        raise HTTPException(status_code=500, detail="Failed to add relation")


# =============================================================================
# Query / Search / Stats
# =============================================================================


@router.post("/query", response_model=QueryResponse, dependencies=_CLOSED_UNTIL_ORG_SCOPING)
async def query_knowledge_base(
    body: QueryRequest,
    auth: AuthorizationContext = Depends(require_authenticated),
    engine: Any = Depends(get_query_engine),
) -> QueryResponse:
    """
    Natural language query against the knowledge base.

    Runs a question through the query engine, which uses facts and embeddings
    to produce an answer with citations.
    """
    org_id = _caller_org(auth, "Querying knowledge")
    try:
        options_data = body.options
        options = QueryOptions(
            max_chunks=options_data.get("max_chunks", 10),
            search_alpha=options_data.get("search_alpha", 0.5),
            use_agents=options_data.get("use_agents", False),
            extract_facts=options_data.get("extract_facts", True),
            include_citations=options_data.get("include_citations", True),
        )

        try:
            result = await _await_if_needed(
                engine.query(body.question, body.workspace_id, options, org_id=org_id)
            )
        except (KeyError, ValueError, OSError, TypeError, RuntimeError) as e:
            logger.error("Query execution failed: %s", e)
            raise HTTPException(status_code=500, detail="Query execution failed")

        result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
        return QueryResponse(
            answer=result_dict.get("answer", ""),
            confidence=result_dict.get("confidence", 0.0),
            citations=result_dict.get("citations", []),
            sources=result_dict.get("sources", []),
            **{
                k: v
                for k, v in result_dict.items()
                if k not in ("answer", "confidence", "citations", "sources")
            },
        )

    except HTTPException:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error in knowledge base query: %s", e)
        raise HTTPException(status_code=500, detail="Failed to execute query")


@router.get("/search", response_model=SearchResponse, dependencies=_CLOSED_UNTIL_ORG_SCOPING)
async def search_knowledge_base(
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    workspace_id: str = Query("default", max_length=100, description="Workspace to search"),
    limit: int = Query(10, ge=1, le=50, description="Max results"),
    auth: AuthorizationContext = Depends(require_authenticated),
    engine: Any = Depends(get_query_engine),
) -> SearchResponse:
    """
    Search knowledge base chunks via embeddings.

    Performs a vector similarity search over the caller's organization's
    chunks and returns ranked results; a caller without an organization
    gets 403 ``knowledge_org_required``.
    """
    org_id = _caller_org(auth, "Searching knowledge")
    try:
        if not hasattr(engine, "search"):
            raise HTTPException(
                status_code=501,
                detail="Query engine does not support search",
            )

        try:
            results = await _await_if_needed(engine.search(q, workspace_id, limit, org_id=org_id))
        except (KeyError, ValueError, OSError, TypeError, RuntimeError) as e:
            logger.error("Search failed: %s", e)
            raise HTTPException(status_code=500, detail="Search operation failed")

        return SearchResponse(
            query=q,
            workspace_id=workspace_id,
            results=[r.to_dict() if hasattr(r, "to_dict") else r for r in results],
            count=len(results),
        )

    except HTTPException:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error searching knowledge base: %s", e)
        raise HTTPException(status_code=500, detail="Failed to search knowledge base")


@router.get("/stats", response_model=StatsResponse, dependencies=_CLOSED_UNTIL_ORG_SCOPING)
async def get_stats(
    workspace_id: str | None = Query(None, max_length=100, description="Filter by workspace"),
    auth: AuthorizationContext = Depends(require_authenticated),
    store: Any = Depends(get_fact_store),
) -> StatsResponse:
    """
    Get knowledge base statistics.

    Returns aggregate statistics about facts, relations, and topics,
    optionally scoped to a specific workspace.
    """
    try:
        stats = await _call_store(store, "get_statistics", workspace_id)
        return StatsResponse(
            workspace_id=workspace_id,
            **stats,
        )
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error getting stats: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get knowledge base stats")


# =============================================================================
# Import / Export / Sync Status
# =============================================================================


@router.get("/export", response_model=ExportResponse, dependencies=_CLOSED_UNTIL_ORG_SCOPING)
async def export_knowledge_base(
    workspace_id: str | None = Query(None, max_length=100, description="Workspace to export"),
    format: str = Query("json", description="Export format (json)"),
    auth: AuthorizationContext = Depends(require_authenticated),
    store: Any = Depends(get_fact_store),
) -> ExportResponse:
    """
    Export knowledge base facts.

    Returns all facts (optionally filtered by workspace) in the requested
    format for backup or transfer purposes.
    """
    try:
        from datetime import datetime, timezone

        # Retrieve all facts via listing with a high limit
        filters = FactFilters(
            workspace_id=workspace_id,
            include_superseded=True,
            limit=10000,
            offset=0,
        )
        facts = await _call_store(store, "list_facts", filters)
        fact_dicts = [f.to_dict() if hasattr(f, "to_dict") else f for f in facts]

        return ExportResponse(
            format=format,
            facts=fact_dicts,
            total=len(fact_dicts),
            exported_at=datetime.now(timezone.utc).isoformat(),
        )
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error exporting knowledge base: %s", e)
        raise HTTPException(status_code=500, detail="Failed to export knowledge base")


@router.post("/import", response_model=ImportResponse, status_code=201)
async def import_knowledge_base(
    body: ImportRequest,
    auth: AuthorizationContext = Depends(require_permission("knowledge:write")),
    store: Any = Depends(get_fact_store),
) -> ImportResponse:
    """
    Import knowledge entries.

    Accepts a list of fact dictionaries and imports them into the knowledge
    base. The only merge strategy is ``skip_existing`` (the default); any
    other value answers 422 before the fact store is read or written.
    Every fact is bound to the caller's organization. An entry whose ``id``
    is already stored in that organization, or whose statement is already
    stored in that organization and workspace, is counted in ``skipped``,
    not ``imported``.

    Requires ``knowledge:write`` permission.
    """
    org_id = _caller_org(auth)
    imported = 0
    skipped = 0
    errors = 0
    details: list[str] = []

    for fact_data in body.facts:
        try:
            statement = fact_data.get("statement", "")
            if not statement:
                skipped += 1
                details.append(f"Skipped entry without statement: {fact_data.get('id', 'unknown')}")
                continue

            fact_id = fact_data.get("id")
            if fact_id:
                existing = await _call_store(store, "get_fact", fact_id, org_id=org_id)
                if existing:
                    skipped += 1
                    continue

            workspace_id = fact_data.get("workspace_id", body.workspace_id)
            if await _call_store(store, "find_duplicate", statement, workspace_id, org_id=org_id):
                skipped += 1
                continue

            await _call_store(
                store,
                "add_fact",
                statement=statement,
                workspace_id=workspace_id,
                evidence_ids=fact_data.get("evidence_ids", []),
                source_documents=fact_data.get("source_documents", []),
                confidence=fact_data.get("confidence", 0.5),
                topics=fact_data.get("topics", []),
                metadata=fact_data.get("metadata", {}),
                org_id=org_id,
            )
            imported += 1

        except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
            errors += 1
            details.append(f"Error importing {fact_data.get('id', 'unknown')}: {type(e).__name__}")
            logger.warning("Error importing fact: %s", e)

    return ImportResponse(
        imported=imported,
        skipped=skipped,
        errors=errors,
        total=len(body.facts),
        details=details,
    )


@router.get("/sync-status", response_model=SyncStatusResponse)
async def get_sync_status(
    auth: AuthorizationContext = Depends(require_authenticated),
    store: Any = Depends(get_fact_store),
) -> SyncStatusResponse:
    """
    Get knowledge base synchronization status.

    Returns whether the knowledge base is synced, the last sync timestamp,
    and the number of pending changes.
    """
    try:
        # Try to get sync info from the store
        if hasattr(store, "get_sync_status"):
            sync_info = await _call_store(store, "get_sync_status")
            if isinstance(sync_info, dict):
                return SyncStatusResponse(
                    synced=sync_info.get("synced", True),
                    last_sync_at=sync_info.get("last_sync_at"),
                    pending_changes=sync_info.get("pending_changes", 0),
                    status=sync_info.get("status", "ok"),
                )

        # Default: report as synced if no sync mechanism
        return SyncStatusResponse(
            synced=True,
            last_sync_at=None,
            pending_changes=0,
            status="ok",
        )

    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error getting sync status: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get sync status")
