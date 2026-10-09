"""
Search Operations Mixin for Knowledge Handler.

Provides chunk search and statistics operations.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from aragora.server.http_utils import run_async as _run_async
from aragora.rbac.decorators import require_permission

from ..base import (
    HandlerResult,
    error_response,
    get_bounded_float_param,
    get_bounded_string_param,
    get_clamped_int_param,
    handle_errors,
    json_response,
    ttl_cache,
)
from ..openapi_decorator import api_endpoint

if TYPE_CHECKING:
    from aragora.knowledge import DatasetQueryEngine, FactStore, SimpleQueryEngine

try:
    from aragora.knowledge.mound.retrieval import KnowledgeMoundRetriever
except ImportError:  # pragma: no cover - optional KM subsystem
    KnowledgeMoundRetriever = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# Cache TTLs
CACHE_TTL_STATS = 300  # 5 minutes for statistics


class SearchHandlerProtocol(Protocol):
    """Protocol for handlers that use SearchOperationsMixin."""

    def _get_fact_store(self) -> FactStore: ...
    def _get_query_engine(self) -> DatasetQueryEngine | SimpleQueryEngine: ...
    def _get_knowledge_mound(self) -> Any | None: ...


def _extract_search_query(query_params: dict[str, Any]) -> str:
    """Accept both legacy `q` and frontend-friendly `query` parameters."""
    query = get_bounded_string_param(query_params, "q", "", max_length=500)
    if query:
        return query
    return get_bounded_string_param(query_params, "query", "", max_length=500)  # type: ignore[return-value]


def _normalize_search_result(result: Any) -> dict[str, Any]:
    """Normalize chunk or KM item results into one frontend-friendly shape."""
    if isinstance(result, dict):
        raw: dict[str, Any] = dict(result)
    elif hasattr(result, "to_dict"):
        raw = result.to_dict()
    else:
        raw = {}
        for field in (
            "id",
            "item_id",
            "node_id",
            "chunk_id",
            "document_id",
            "workspace_id",
            "content",
            "score",
            "confidence",
            "node_type",
            "domain",
            "metadata",
            "title",
            "source",
            "topics",
            "tags",
        ):
            value = getattr(result, field, None)
            if value is not None:
                raw[field] = value

    metadata = raw.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    metadata = dict(metadata)

    result_id = (
        raw.get("node_id")
        or raw.get("id")
        or raw.get("item_id")
        or raw.get("chunk_id")
        or raw.get("document_id")
        or ""
    )

    score = raw.get("score", raw.get("relevance_score", raw.get("similarity", 0.0)))
    try:
        score_value = float(score)
    except (TypeError, ValueError):
        score_value = 0.0

    confidence = raw.get("confidence", score_value)
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        confidence_value = 0.0

    if raw.get("title") is not None and "title" not in metadata:
        metadata["title"] = raw["title"]
    if raw.get("source") is not None and "source" not in metadata:
        metadata["source"] = raw["source"]
    if raw.get("topics") is not None and "topics" not in metadata:
        metadata["topics"] = raw["topics"]
    if raw.get("tags") is not None and "tags" not in metadata:
        metadata["tags"] = raw["tags"]
    if raw.get("domain") is not None and "domain" not in metadata:
        metadata["domain"] = raw["domain"]

    normalized = dict(raw)
    normalized["node_id"] = result_id
    normalized.setdefault("chunk_id", result_id)
    normalized.setdefault("document_id", metadata.get("document_id", ""))
    normalized.setdefault("workspace_id", raw.get("workspace_id", metadata.get("workspace_id", "")))
    normalized["content"] = str(raw.get("content", ""))
    normalized["score"] = score_value
    normalized["confidence"] = confidence_value
    normalized["node_type"] = (
        raw.get("node_type") or raw.get("content_type") or metadata.get("node_type") or "chunk"
    )
    normalized["domain"] = raw.get("domain", metadata.get("domain"))
    normalized["metadata"] = metadata
    return normalized


def _filter_normalized_results(
    results: list[dict[str, Any]],
    *,
    min_confidence: float,
    domain: str | None,
) -> list[dict[str, Any]]:
    """Apply lightweight frontend filters consistently across backends."""
    filtered: list[dict[str, Any]] = []
    for result in results:
        confidence = result.get("confidence", 0.0)
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 0.0
        if confidence_value < min_confidence:
            continue

        if domain:
            result_domain = result.get("domain") or result.get("metadata", {}).get("domain")
            if str(result_domain or "").strip() != domain:
                continue

        filtered.append(result)
    return filtered


class SearchOperationsMixin:
    """Mixin providing search and stats operations for KnowledgeHandler."""

    @api_endpoint(
        method="GET",
        path="/api/v1/knowledge/search",
        summary="Search knowledge base chunks via embeddings",
        tags=["Knowledge Base"],
        parameters=[
            {
                "name": "q",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
                "description": "Search query string (max 500 chars)",
            },
            {
                "name": "workspace_id",
                "in": "query",
                "schema": {"type": "string", "default": "default"},
                "description": "Workspace to search within",
            },
            {
                "name": "limit",
                "in": "query",
                "schema": {"type": "integer", "default": 10},
                "description": "Maximum number of results (1-50)",
            },
        ],
        responses={
            "200": {
                "description": "Search results with matching chunks",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "workspace_id": {"type": "string"},
                                "results": {"type": "array", "items": {"type": "object"}},
                                "count": {"type": "integer"},
                            },
                        }
                    }
                },
            },
            "400": {"description": "Missing query parameter"},
            "401": {"description": "Unauthorized"},
            "403": {"description": "Forbidden"},
            "500": {"description": "Search failed"},
        },
    )
    @handle_errors("search chunks")
    @require_permission("knowledge:read")
    def _handle_search(
        self: SearchHandlerProtocol, query_params: dict, handler: Any = None
    ) -> HandlerResult:
        """Handle GET /api/knowledge/search - Search chunks.

        ``handler`` is unused here; ``@require_permission`` reads the request's
        authorization context from it.
        """

        query = _extract_search_query(query_params)
        if not query:
            return error_response("Query parameter 'q' or 'query' is required", 400)

        workspace_id = get_bounded_string_param(
            query_params, "workspace_id", "default", max_length=100
        )
        limit = get_clamped_int_param(query_params, "limit", 10, min_val=1, max_val=50)
        min_confidence = get_bounded_float_param(
            query_params, "min_confidence", 0.0, min_val=0.0, max_val=1.0
        )
        domain = get_bounded_string_param(query_params, "domain", None, max_length=100)

        mound_getter = getattr(self, "_get_knowledge_mound", None)
        mound = mound_getter() if callable(mound_getter) else None
        if mound and KnowledgeMoundRetriever is not None:
            retriever = KnowledgeMoundRetriever(
                mound,
                min_confidence=min_confidence,
                default_limit=limit,
            )
            if retriever.is_available():
                try:
                    retrieved = _run_async(
                        retriever.retrieve(
                            query,
                            limit=limit,
                            workspace_id=workspace_id,
                        )
                    )
                except (
                    KeyError,
                    ValueError,
                    OSError,
                    TypeError,
                    RuntimeError,
                    AttributeError,
                    ConnectionError,
                ) as e:
                    logger.error("Knowledge Mound search failed: %s", e)
                    return error_response("Search operation failed", 500)

                normalized = []
                if retrieved is not None:
                    items = getattr(retrieved, "items", retrieved)
                    normalized = [_normalize_search_result(item) for item in items]  # type: ignore[union-attr]
                normalized = _filter_normalized_results(
                    normalized,
                    min_confidence=min_confidence,
                    domain=domain,
                )

                return json_response(
                    {
                        "query": query,
                        "workspace_id": workspace_id,
                        "results": normalized[:limit],
                        "count": len(normalized[:limit]),
                        "total": len(normalized[:limit]),
                        "search_backend": "knowledge_mound",
                    }
                )

        engine = self._get_query_engine()
        if not hasattr(engine, "search"):
            raise TypeError("Query engine does not support search")
        try:
            results = _run_async(engine.search(query, workspace_id, limit))  # type: ignore[arg-type]
        except (KeyError, ValueError, OSError, TypeError, RuntimeError) as e:
            logger.error("Search failed: %s", e)
            return error_response("Search operation failed", 500)

        normalized_results = [_normalize_search_result(result) for result in results]
        normalized_results = _filter_normalized_results(
            normalized_results,
            min_confidence=min_confidence,
            domain=domain,
        )

        return json_response(
            {
                "query": query,
                "workspace_id": workspace_id,
                "results": normalized_results,
                "count": len(normalized_results),
                "total": len(normalized_results),
                "search_backend": "query_engine",
            }
        )

    @api_endpoint(
        method="GET",
        path="/api/v1/knowledge/stats",
        summary="Get knowledge base statistics",
        tags=["Knowledge Base"],
        operation_id="get_knowledge_stats",
        parameters=[
            {
                "name": "workspace_id",
                "in": "query",
                "schema": {"type": "string"},
                "description": "Filter statistics by workspace ID",
            },
        ],
        responses={
            "200": {
                "description": "Knowledge base statistics",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "workspace_id": {"type": "string"},
                            },
                            "additionalProperties": True,
                        }
                    }
                },
            },
            "401": {"description": "Unauthorized"},
            "403": {"description": "Forbidden"},
        },
    )
    @ttl_cache(ttl_seconds=CACHE_TTL_STATS, key_prefix="knowledge_stats", skip_first=True)
    @handle_errors("get stats")
    def _handle_stats(self: SearchHandlerProtocol, workspace_id: str | None) -> HandlerResult:
        """Handle GET /api/knowledge/stats - Get statistics."""
        store = self._get_fact_store()
        stats = store.get_statistics(workspace_id)

        return json_response(
            {
                "workspace_id": workspace_id,
                **stats,
            }
        )
