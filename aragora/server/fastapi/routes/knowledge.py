"""
Knowledge Endpoints (FastAPI v2).

Migrated from: aragora/server/handlers/knowledge/ (aiohttp handler)

Provides async knowledge mound management endpoints:
- GET  /api/v2/knowledge/search          - Search knowledge mound (query param)
- POST /api/v2/knowledge/search          - Semantic search (JSON body)
- GET  /api/v2/knowledge/stats           - Knowledge mound statistics
- GET  /api/v2/knowledge/gaps            - Knowledge gap detection
- GET  /api/v2/knowledge/adapters        - List KM adapters
- GET  /api/v2/knowledge/staleness       - Staleness analysis
- POST /api/v2/knowledge/query           - Structured query with filters
- GET  /api/v2/knowledge/items/{item_id} - Get knowledge item by ID
- POST /api/v2/knowledge/items           - Ingest a new knowledge item
- DELETE /api/v2/knowledge/{item_id}     - Delete knowledge item

Migration Notes:
    This module replaces the legacy knowledge handler endpoints with native
    FastAPI routes. Key improvements:
    - Pydantic request/response models with automatic validation
    - FastAPI dependency injection for auth and storage
    - Proper HTTP status codes (422 for validation, 404 for not found)
    - OpenAPI schema auto-generation

Access: reads require ``knowledge:read`` and writes ``knowledge:write``. Every route
also requires the caller's organization (403 ``knowledge_org_required`` without one).
Mound items are returned only when ``metadata["org_id"]`` equals the caller's
organization; unstamped items are withheld. Writes are stamped with the caller's
organization, never one taken from the request body. Counts (stats, staleness
totals, gap counts) remain Mound-wide aggregates.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from enum import Enum
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from aragora.rbac.models import AuthorizationContext

from ..dependencies.auth import require_permission
from ..middleware.error_handling import APIError, NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", tags=["Knowledge"])

MOUND_ORG_KEY = "org_id"
# Candidates read per search before the org filter; reads never page with offset
# because Mound.query re-ranks every read and applies the offset after ranking.
_ORG_READ_WINDOW = 100


# =============================================================================
# Pydantic Models
# =============================================================================


class KnowledgeItemSummary(BaseModel):
    """Summary of a knowledge item for list/search views."""

    id: str
    title: str = ""
    content_type: str = "text"
    source: str = ""
    confidence: float = 0.0
    created_at: str | None = None
    tags: list[str] = Field(default_factory=list)
    relevance_score: float = 0.0

    model_config = {"extra": "allow"}


class KnowledgeSearchResponse(BaseModel):
    """Response for knowledge search."""

    items: list[KnowledgeItemSummary]
    total: int
    query: str


class KnowledgeItemDetail(BaseModel):
    """Full knowledge item details."""

    id: str
    title: str = ""
    content: str = ""
    content_type: str = "text"
    source: str = ""
    confidence: float = 0.0
    created_at: str | None = None
    updated_at: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    debate_id: str | None = None
    adapter: str | None = None

    model_config = {"extra": "allow"}


class IngestKnowledgeRequest(BaseModel):
    """Request body for POST /knowledge/items."""

    title: str = Field(..., min_length=1, max_length=500, description="Item title")
    content: str = Field(..., min_length=1, description="Item content")
    content_type: str = Field("text", description="Content type (text, url, document)")
    source: str = Field("api", description="Source identifier")
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class IngestKnowledgeResponse(BaseModel):
    """Response for POST /knowledge/items."""

    success: bool
    item_id: str
    item: KnowledgeItemDetail


class KnowledgeStatsResponse(BaseModel):
    """Response for knowledge mound statistics."""

    total_items: int = 0
    adapters: list[str] = Field(default_factory=list)
    items_by_type: dict[str, int] = Field(default_factory=dict)
    items_by_source: dict[str, int] = Field(default_factory=dict)
    last_ingested_at: str | None = None
    storage_backend: str = "unknown"


class AdapterInfo(BaseModel):
    """Information about a Knowledge Mound adapter."""

    name: str
    description: str = ""
    status: str = "active"

    model_config = {"extra": "allow"}


class AdapterListResponse(BaseModel):
    """Response for adapter listing."""

    adapters: list[AdapterInfo]
    total: int


class SemanticSearchRequest(BaseModel):
    """Request body for POST /knowledge/search (semantic search)."""

    query: str = Field(..., min_length=1, description="Semantic search query")
    limit: int = Field(20, ge=1, le=100, description="Max results to return")
    content_type: str | None = Field(None, description="Filter by content type")
    source: str | None = Field(None, description="Filter by source")


class StructuredQueryRequest(BaseModel):
    """Request body for POST /knowledge/query."""

    query: str = Field(..., min_length=1, description="Query string")
    content_type: str | None = Field(None, description="Filter by content type")
    source: str | None = Field(None, description="Filter by source")
    adapter: str | None = Field(None, description="Filter by adapter")
    tags: list[str] = Field(default_factory=list, description="Filter by tags")
    min_confidence: float = Field(0.0, ge=0.0, le=1.0, description="Minimum confidence")
    limit: int = Field(20, ge=1, le=100, description="Max results to return")


class StructuredQueryResponse(BaseModel):
    """Response for structured knowledge query."""

    items: list[KnowledgeItemSummary]
    total: int
    query: str
    filters_applied: dict[str, Any] = Field(default_factory=dict)


class StalenessItem(BaseModel):
    """A single item with staleness info."""

    id: str
    title: str = ""
    source: str = ""
    created_at: str | None = None
    updated_at: str | None = None
    age_days: float = 0.0
    stale: bool = False

    model_config = {"extra": "allow"}


class StalenessResponse(BaseModel):
    """Response for staleness analysis."""

    total_items: int = 0
    stale_items: int = 0
    stale_percent: float = 0.0
    items: list[StalenessItem] = Field(default_factory=list)
    threshold_days: float = 30.0
    storage_backend: str = ""


class DeleteKnowledgeResponse(BaseModel):
    """Response for knowledge item deletion."""

    success: bool
    item_id: str
    message: str = ""


class CoverageGap(BaseModel):
    """A single coverage gap in knowledge."""

    domain: str = ""
    description: str = ""
    severity: str = "medium"
    recommendation: str = ""

    model_config = {"extra": "allow"}


class KnowledgeGapsResponse(BaseModel):
    """Response for knowledge gap detection."""

    workspace_id: str = "default"
    coverage_gaps: list[CoverageGap] = Field(default_factory=list)
    stale_entries: list[StalenessItem] = Field(default_factory=list)
    stale_count: int = 0
    contradictions: list[dict[str, Any]] = Field(default_factory=list)
    contradiction_count: int = 0
    status: str = "ok"


# =============================================================================
# Dependencies
# =============================================================================


async def get_knowledge_mound(request: Request):
    """Dependency to get the Knowledge Mound from app state."""
    ctx = getattr(request.app.state, "context", None)
    if ctx:
        km = ctx.get("knowledge_mound")
        if km:
            return km

    # Fall back to global knowledge mound
    try:
        from aragora.knowledge.mound import get_knowledge_mound as _get_km

        return _get_km()
    except (ImportError, RuntimeError, OSError, ValueError) as e:
        logger.warning("Knowledge Mound not available: %s", e)
        return None


async def _call_km_method(km: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
    """Run Knowledge Mound methods without blocking the FastAPI event loop."""
    method = getattr(km, method_name)
    if inspect.iscoroutinefunction(method):
        return await method(*args, **kwargs)
    result = await asyncio.to_thread(method, *args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


# =============================================================================
# Helpers
# =============================================================================


def _caller_org(auth: AuthorizationContext) -> str:
    """The organization every Mound read and write is confined to (verified auth only)."""
    if not auth.org_id:
        raise APIError(
            "Knowledge Mound access requires an organization",
            status_code=403,
            code="knowledge_org_required",
        )
    return auth.org_id


def _item_org(entry: Any) -> str | None:
    """The org stamp of a Mound item, an ``(item, score)`` pair, or None when unstamped."""
    if isinstance(entry, tuple) and len(entry) == 2:
        entry = entry[0]
    metadata = (
        entry.get("metadata") if isinstance(entry, dict) else getattr(entry, "metadata", None)
    )
    org_id = metadata.get(MOUND_ORG_KEY) if isinstance(metadata, dict) else None
    return org_id if isinstance(org_id, str) and org_id else None


def _for_org(entries: Any, org_id: str) -> list[Any]:
    """Entries stamped with ``org_id``; unstamped and other-org entries are withheld."""
    kept = [entry for entry in entries or [] if _item_org(entry) == org_id]
    if len(kept) < len(entries or []):
        logger.debug("Withheld %d Mound entries outside the caller's org", len(entries) - len(kept))
    return kept


def _result_entries(results: Any) -> list[Any]:
    """Stock ``KnowledgeMound.query`` returns a ``QueryResult``; other backends a list."""
    entries = getattr(results, "items", results)
    return list(entries) if isinstance(entries, (list, tuple)) else []


async def _search_for_org(
    km: Any, methods: tuple[str, str], query: str, org_id: str, **filters: Any
) -> list[KnowledgeItemSummary]:
    """Run the first available search method and keep only the caller's org items."""
    method = next((name for name in methods if hasattr(km, name)), None)
    if method is None:
        return []
    results = await _call_km_method(km, method, query, limit=_ORG_READ_WINDOW, **filters)
    summaries: list[KnowledgeItemSummary] = []
    for result in _for_org(_result_entries(results), org_id):
        if isinstance(result, tuple) and len(result) == 2:
            item, score = result
            summaries.append(_item_to_summary(item, relevance=float(score)))
        else:
            summaries.append(_item_to_summary(result))
    return summaries


async def _get_for_org(km: Any, item_id: str, org_id: str) -> Any:
    """The item when it carries the caller's org stamp; 404 otherwise, as if absent."""
    item = None
    for method in ("get", "get_item", "get_by_id"):
        if hasattr(km, method):
            item = await _call_km_method(km, method, item_id)
            break
    if not item or _item_org(item) != org_id:
        raise NotFoundError(f"Knowledge item {item_id} not found")
    return item


def _plain(value: Any) -> Any:
    """Stock Mound items carry ``KnowledgeSource``/``ConfidenceLevel`` enums."""
    if isinstance(value, Enum):
        return value.to_float() if hasattr(value, "to_float") else value.value
    return value


def _item_to_summary(item: Any, relevance: float = 0.0) -> KnowledgeItemSummary:
    """Convert a knowledge item to a summary."""
    if isinstance(item, dict):
        return KnowledgeItemSummary(
            id=item.get("id") or item.get("item_id") or "",
            title=item.get("title", ""),
            content_type=item.get("content_type", "text"),
            source=item.get("source", ""),
            confidence=item.get("confidence", 0.0),
            created_at=item.get("created_at"),
            tags=item.get("tags", []),
            relevance_score=item.get("relevance_score", relevance),
        )
    return KnowledgeItemSummary(
        id=getattr(item, "id", getattr(item, "item_id", "")),
        title=getattr(item, "title", ""),
        content_type=getattr(item, "content_type", "text"),
        source=_plain(getattr(item, "source", "")),
        confidence=_plain(getattr(item, "confidence", 0.0)),
        created_at=str(getattr(item, "created_at", "")) if hasattr(item, "created_at") else None,
        tags=getattr(item, "tags", []),
        relevance_score=getattr(item, "relevance_score", relevance),
    )


def _item_to_detail(item: Any) -> KnowledgeItemDetail:
    """Convert a knowledge item to full detail."""
    if isinstance(item, dict):
        return KnowledgeItemDetail(
            id=item.get("id") or item.get("item_id") or "",
            title=item.get("title", ""),
            content=item.get("content", ""),
            content_type=item.get("content_type", "text"),
            source=item.get("source", ""),
            confidence=item.get("confidence", 0.0),
            created_at=item.get("created_at"),
            updated_at=item.get("updated_at"),
            tags=item.get("tags", []),
            metadata=item.get("metadata", {}),
            debate_id=item.get("debate_id"),
            adapter=item.get("adapter"),
        )
    return KnowledgeItemDetail(
        id=getattr(item, "id", getattr(item, "item_id", "")),
        title=getattr(item, "title", ""),
        content=getattr(item, "content", ""),
        content_type=getattr(item, "content_type", "text"),
        source=_plain(getattr(item, "source", "")),
        confidence=_plain(getattr(item, "confidence", 0.0)),
        created_at=str(getattr(item, "created_at", "")) if hasattr(item, "created_at") else None,
        updated_at=str(getattr(item, "updated_at", "")) if hasattr(item, "updated_at") else None,
        tags=getattr(item, "tags", []),
        metadata=getattr(item, "metadata", {}),
        debate_id=getattr(item, "debate_id", None),
        adapter=getattr(item, "adapter", None),
    )


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/knowledge/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    request: Request,
    query: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100, description="Max results to return"),
    content_type: str | None = Query(None, description="Filter by content type"),
    source: str | None = Query(None, description="Filter by source"),
    auth: AuthorizationContext = Depends(require_permission("knowledge:read")),
    km=Depends(get_knowledge_mound),
) -> KnowledgeSearchResponse:
    """
    Search the knowledge mound.

    Returns knowledge items matching the query with relevance scoring.
    Supports filtering by content type and source.
    Requires `knowledge:read`; returns only items stamped with the caller's org.
    """
    org_id = _caller_org(auth)
    if not km:
        raise HTTPException(status_code=503, detail="Knowledge Mound not available")

    try:
        filters: dict[str, Any] = {}
        if content_type:
            filters["content_type"] = content_type
        if source:
            filters["source"] = source

        items = await _search_for_org(km, ("search", "query"), query, org_id, **filters)

        return KnowledgeSearchResponse(
            items=items[:limit],
            total=len(items),
            query=query,
        )

    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error searching knowledge: %s", e)
        raise HTTPException(status_code=500, detail="Failed to search knowledge")


@router.post("/knowledge/search", response_model=KnowledgeSearchResponse)
async def search_knowledge_post(
    body: SemanticSearchRequest,
    request: Request,
    auth: AuthorizationContext = Depends(require_permission("knowledge:read")),
    km=Depends(get_knowledge_mound),
) -> KnowledgeSearchResponse:
    """
    Semantic search of the knowledge mound (POST variant).

    Accepts a JSON body with query and filters. Returns knowledge items
    matching the query with relevance scoring.
    """
    return await search_knowledge(
        request=request,
        query=body.query,
        limit=body.limit,
        content_type=body.content_type,
        source=body.source,
        auth=auth,
        km=km,
    )


@router.get("/knowledge/stats", response_model=KnowledgeStatsResponse)
async def get_knowledge_stats(
    request: Request,
    auth: AuthorizationContext = Depends(require_permission("knowledge:read")),
    km=Depends(get_knowledge_mound),
) -> KnowledgeStatsResponse:
    """
    Get knowledge mound statistics.

    Returns aggregate statistics about the knowledge mound including
    item counts, adapter info, and storage details.
    """
    _caller_org(auth)
    if not km:
        return KnowledgeStatsResponse(storage_backend="not_initialized")

    try:
        stats: dict[str, Any] = {}

        if hasattr(km, "get_stats"):
            raw_stats = await _call_km_method(km, "get_stats")
            if isinstance(raw_stats, dict):
                stats = raw_stats
        elif hasattr(km, "stats"):
            raw_stats = await _call_km_method(km, "stats")
            if isinstance(raw_stats, dict):
                stats = raw_stats

        # Get adapter list
        adapters: list[str] = []
        if hasattr(km, "list_adapters"):
            try:
                adapters = [str(a) for a in await _call_km_method(km, "list_adapters")]
            except (RuntimeError, TypeError, AttributeError):
                pass

        return KnowledgeStatsResponse(
            total_items=stats.get("total_items", stats.get("count", 0)),
            adapters=adapters,
            items_by_type=stats.get("items_by_type", {}),
            items_by_source=stats.get("items_by_source", {}),
            last_ingested_at=stats.get("last_ingested_at"),
            storage_backend=stats.get("storage_backend", "sqlite"),
        )

    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error getting knowledge stats: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get knowledge stats")


@router.get("/knowledge/gaps", response_model=KnowledgeGapsResponse)
async def get_knowledge_gaps(
    request: Request,
    domain: str | None = Query(None, description="Domain to check for coverage gaps"),
    max_age_days: int = Query(
        90, ge=1, le=365, description="Max age in days before an item is stale"
    ),
    workspace_id: str = Query("default", description="Workspace ID"),
    auth: AuthorizationContext = Depends(require_permission("knowledge:read")),
    km=Depends(get_knowledge_mound),
) -> KnowledgeGapsResponse:
    """
    Detect knowledge gaps including coverage gaps, staleness, and contradictions.

    Uses the KnowledgeGapDetector to analyze the knowledge mound for areas
    that need attention: missing coverage, stale entries, and contradictions.
    Stale entries and contradictions are limited to the caller's org stamp.
    """
    org_id = _caller_org(auth)
    if not km:
        return KnowledgeGapsResponse(
            workspace_id=workspace_id,
            status="knowledge_mound_unavailable",
        )

    try:
        # Try to use the KnowledgeGapDetector
        try:
            from aragora.knowledge.gap_detector import KnowledgeGapDetector

            detector = KnowledgeGapDetector(mound=km, workspace_id=workspace_id)

            coverage_gaps: list[CoverageGap] = []
            if domain:
                raw_gaps = await detector.detect_coverage_gaps(domain)
                for g in raw_gaps:
                    g_dict = g.to_dict() if hasattr(g, "to_dict") else g
                    if isinstance(g_dict, dict):
                        coverage_gaps.append(
                            CoverageGap(
                                domain=g_dict.get("domain", domain),
                                description=g_dict.get("description", ""),
                                severity=g_dict.get("severity", "medium"),
                                recommendation=g_dict.get("recommendation", ""),
                            )
                        )

            stale = await detector.detect_staleness(max_age_days=max_age_days)
            stale_entries: list[StalenessItem] = []
            for s in _for_org(stale, org_id)[:50]:
                s_dict = s.to_dict() if hasattr(s, "to_dict") else s
                if isinstance(s_dict, dict):
                    stale_entries.append(
                        StalenessItem(
                            id=s_dict.get("id", ""),
                            title=s_dict.get("title", ""),
                            source=s_dict.get("source", ""),
                            created_at=s_dict.get("created_at"),
                            updated_at=s_dict.get("updated_at"),
                            age_days=s_dict.get("age_days", 0.0),
                            stale=True,
                        )
                    )

            raw_contradictions = await detector.detect_contradictions()
            contradictions: list[dict[str, Any]] = []
            for contradiction in _for_org(raw_contradictions, org_id)[:50]:
                contradiction_dict = (
                    contradiction.to_dict() if hasattr(contradiction, "to_dict") else contradiction
                )
                if isinstance(contradiction_dict, dict):
                    contradictions.append(contradiction_dict)

            return KnowledgeGapsResponse(
                workspace_id=workspace_id,
                coverage_gaps=coverage_gaps,
                stale_entries=stale_entries,
                stale_count=len(stale),  # type: ignore[arg-type]
                contradictions=contradictions,
                contradiction_count=len(raw_contradictions),  # type: ignore[arg-type]
                status="ok",
            )

        except (ImportError, RuntimeError) as e:
            logger.debug("KnowledgeGapDetector not available: %s", e)

            # Fall back to basic staleness from KM stats
            return KnowledgeGapsResponse(
                workspace_id=workspace_id,
                status="gap_detector_unavailable",
            )

    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error detecting knowledge gaps: %s", e)
        raise HTTPException(status_code=500, detail="Failed to detect knowledge gaps")


@router.get("/knowledge/items/{item_id}", response_model=KnowledgeItemDetail)
async def get_knowledge_item(
    item_id: str,
    auth: AuthorizationContext = Depends(require_permission("knowledge:read")),
    km=Depends(get_knowledge_mound),
) -> KnowledgeItemDetail:
    """
    Get knowledge item by ID.

    Returns full details of a specific knowledge item including content and metadata.
    Items not stamped with the caller's org answer 404.
    """
    org_id = _caller_org(auth)
    if not km:
        raise HTTPException(status_code=503, detail="Knowledge Mound not available")

    try:
        return _item_to_detail(await _get_for_org(km, item_id, org_id))

    except NotFoundError:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error getting knowledge item %s: %s", item_id, e)
        raise HTTPException(status_code=500, detail="Failed to get knowledge item")


@router.post("/knowledge/items", response_model=IngestKnowledgeResponse, status_code=201)
async def ingest_knowledge_item(
    body: IngestKnowledgeRequest,
    auth: AuthorizationContext = Depends(require_permission("knowledge:write")),
    km=Depends(get_knowledge_mound),
) -> IngestKnowledgeResponse:
    """
    Ingest a new knowledge item.

    Adds a knowledge item to the mound for future debate context.
    Requires `knowledge:write` permission. The item is stamped with the
    caller's org; an org in the body metadata is overwritten.
    """
    org_id = _caller_org(auth)
    if not km:
        raise HTTPException(status_code=503, detail="Knowledge Mound not available")

    try:
        import uuid

        item_id = f"ki_{uuid.uuid4().hex[:12]}"
        metadata = {**body.metadata, MOUND_ORG_KEY: org_id}

        item_data: dict[str, Any] = {
            "id": item_id,
            "title": body.title,
            "content": body.content,
            "content_type": body.content_type,
            "source": body.source,
            "tags": body.tags,
            "metadata": metadata,
        }

        # Try to ingest via the knowledge mound API
        if hasattr(km, "ingest"):
            await _call_km_method(km, "ingest", item_data)
        elif hasattr(km, "add"):
            await _call_km_method(km, "add", item_data)
        elif hasattr(km, "store"):
            await _call_km_method(km, "store", item_data)
        else:
            logger.warning("Knowledge Mound has no ingest/add/store method")

        logger.info("Ingested knowledge item: %s (source=%s)", item_id, body.source)

        return IngestKnowledgeResponse(
            success=True,
            item_id=item_id,
            item=KnowledgeItemDetail(
                id=item_id,
                title=body.title,
                content=body.content,
                content_type=body.content_type,
                source=body.source,
                tags=body.tags,
                metadata=metadata,
            ),
        )

    except HTTPException:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error ingesting knowledge item: %s", e)
        raise HTTPException(status_code=500, detail="Failed to ingest knowledge item")


# =============================================================================
# New Endpoints (Adapters, Structured Query, Staleness, Delete)
# =============================================================================


@router.get("/knowledge/adapters", response_model=AdapterListResponse)
async def list_adapters(
    request: Request,
    auth: AuthorizationContext = Depends(require_permission("knowledge:read")),
    km=Depends(get_knowledge_mound),
) -> AdapterListResponse:
    """List available Knowledge Mound adapters."""
    _caller_org(auth)
    if not km:
        return AdapterListResponse(adapters=[], total=0)

    try:
        adapters: list[AdapterInfo] = []

        if hasattr(km, "list_adapters"):
            raw_adapters = await _call_km_method(km, "list_adapters")
            for a in raw_adapters:
                if isinstance(a, str):
                    adapters.append(AdapterInfo(name=a))
                elif isinstance(a, dict):
                    adapters.append(
                        AdapterInfo(
                            name=a.get("name") or a.get("id") or "",
                            description=a.get("description", ""),
                            status=a.get("status", "active"),
                        )
                    )
                else:
                    adapters.append(
                        AdapterInfo(
                            name=getattr(a, "name", getattr(a, "id", str(a))),
                            description=getattr(a, "description", ""),
                            status=getattr(a, "status", "active"),
                        )
                    )

        return AdapterListResponse(adapters=adapters, total=len(adapters))

    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error listing adapters: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list adapters")


@router.post("/knowledge/query", response_model=StructuredQueryResponse)
async def structured_query(
    body: StructuredQueryRequest,
    auth: AuthorizationContext = Depends(require_permission("knowledge:read")),
    km=Depends(get_knowledge_mound),
) -> StructuredQueryResponse:
    """Execute a structured query against the Knowledge Mound with filters.

    Requires `knowledge:read`; returns only items stamped with the caller's org.
    """
    org_id = _caller_org(auth)
    if not km:
        raise HTTPException(status_code=503, detail="Knowledge Mound not available")

    try:
        filters_applied: dict[str, Any] = {}

        search_kwargs: dict[str, Any] = {}
        if body.content_type:
            search_kwargs["content_type"] = body.content_type
            filters_applied["content_type"] = body.content_type
        if body.source:
            search_kwargs["source"] = body.source
            filters_applied["source"] = body.source
        if body.adapter:
            search_kwargs["adapter"] = body.adapter
            filters_applied["adapter"] = body.adapter
        if body.tags:
            search_kwargs["tags"] = body.tags
            filters_applied["tags"] = body.tags
        if body.min_confidence > 0:
            search_kwargs["min_confidence"] = body.min_confidence
            filters_applied["min_confidence"] = body.min_confidence

        items = await _search_for_org(km, ("query", "search"), body.query, org_id, **search_kwargs)

        return StructuredQueryResponse(
            items=items[: body.limit],
            total=len(items),
            query=body.query,
            filters_applied=filters_applied,
        )

    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error in structured query: %s", e)
        raise HTTPException(status_code=500, detail="Failed to execute structured query")


@router.get("/knowledge/staleness", response_model=StalenessResponse)
async def get_staleness_analysis(
    request: Request,
    threshold_days: float = Query(
        30.0, ge=1.0, le=365.0, description="Days before an item is considered stale"
    ),
    limit: int = Query(50, ge=1, le=100, description="Max stale items to return"),  # type: ignore[assignment]
    auth: AuthorizationContext = Depends(require_permission("knowledge:read")),
    km=Depends(get_knowledge_mound),
) -> StalenessResponse:
    """Analyze staleness of knowledge items; listed items are limited to the caller's org."""
    org_id = _caller_org(auth)
    if not km:
        return StalenessResponse(threshold_days=threshold_days)

    try:
        stale_items: list[StalenessItem] = []
        total_items = 0
        stale_count = 0

        # Try dedicated staleness method
        if hasattr(km, "get_staleness"):
            raw = await _call_km_method(
                km, "get_staleness", threshold_days=threshold_days, limit=limit
            )
            if isinstance(raw, dict):
                return StalenessResponse(
                    total_items=raw.get("total_items", 0),
                    stale_items=raw.get("stale_items", 0),
                    stale_percent=raw.get("stale_percent", 0.0),
                    items=[
                        StalenessItem(**i)
                        if isinstance(i, dict)
                        else StalenessItem(
                            id=getattr(i, "id", ""),
                            title=getattr(i, "title", ""),
                        )
                        for i in _for_org(raw.get("items", []), org_id)
                    ],
                    threshold_days=threshold_days,
                )

        # Fall back to stats-based analysis
        if hasattr(km, "get_stats"):
            try:
                raw_stats = await _call_km_method(km, "get_stats")
            except (RuntimeError, OSError, ValueError) as e:
                logger.debug("KM get_stats unavailable for staleness: %s", e)
                raw_stats = None
            if isinstance(raw_stats, dict):
                total_items = int(raw_stats.get("total_items", raw_stats.get("count", 0)) or 0)

        return StalenessResponse(
            total_items=total_items,
            stale_items=stale_count,
            stale_percent=stale_count / total_items * 100 if total_items > 0 else 0.0,
            items=stale_items,
            threshold_days=threshold_days,
        )

    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error in staleness analysis: %s", e)
        raise HTTPException(status_code=500, detail="Failed to analyze staleness")


@router.delete("/knowledge/{item_id}", response_model=DeleteKnowledgeResponse)
async def delete_knowledge_item(
    item_id: str,
    auth: AuthorizationContext = Depends(require_permission("knowledge:write")),
    km=Depends(get_knowledge_mound),
) -> DeleteKnowledgeResponse:
    """Delete a knowledge item by ID. Requires knowledge:write permission.

    Items not stamped with the caller's org answer 404 and are left untouched.
    """
    org_id = _caller_org(auth)
    if not km:
        raise HTTPException(status_code=503, detail="Knowledge Mound not available")

    try:
        await _get_for_org(km, item_id, org_id)

        # Attempt deletion
        deleted = False
        if hasattr(km, "delete"):
            deleted = await _call_km_method(km, "delete", item_id)
        elif hasattr(km, "delete_item"):
            deleted = await _call_km_method(km, "delete_item", item_id)
        elif hasattr(km, "remove"):
            deleted = await _call_km_method(km, "remove", item_id)
        else:
            raise HTTPException(
                status_code=501,
                detail="Knowledge Mound does not support deletion",
            )

        if deleted is False:
            raise HTTPException(status_code=500, detail="Failed to delete knowledge item")

        logger.info("Deleted knowledge item: %s", item_id)

        return DeleteKnowledgeResponse(
            success=True, item_id=item_id, message="Item deleted successfully"
        )

    except NotFoundError:
        raise
    except HTTPException:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error deleting knowledge item %s: %s", item_id, e)
        raise HTTPException(status_code=500, detail="Failed to delete knowledge item")
