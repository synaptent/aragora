"""
Document NL Query endpoint handlers.

Endpoints:
- POST /api/documents/query - Ask questions about documents
- GET/POST /api/documents/search - Keyword search over documents
- POST /api/documents/summarize - Summarize documents
- POST /api/documents/compare - Compare multiple documents
- POST /api/documents/extract - Extract structured information

Every route works on the caller org's stored documents only. A requested
document id of another org or of an unknown owner answers 404 like a missing
one, before any model is called.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from aragora.server.http_utils import run_async as _run_async
from aragora.analysis.nl_query import DocumentQueryEngine, QueryConfig

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
    safe_error_message,
)
from ..utils.params import get_string_param
from aragora.rbac.decorators import require_permission
from aragora.server.validation.query_params import safe_query_int
from aragora.tenancy.record_scope import (
    OrgScope,
    record_not_found,
    record_visible,
    require_org_scope,
)

logger = logging.getLogger(__name__)

_WORD = re.compile(r"\w+")
_MAX_RESULT_CHARS = 8000
_SNIPPET_CHARS = 200


@dataclass
class _DocumentHit:
    """One stored document as a search result (the fields the query engine reads)."""

    document_id: str
    filename: str
    content: str
    combined_score: float
    keyword_score: float
    start_page: int = 0
    heading_context: str = ""

    @property
    def chunk_id(self) -> str:
        return f"{self.document_id}:0"


class _OrgDocumentSearcher:
    """Keyword search over a fixed set of stored documents, one result per document.

    Stands in for the hybrid (vector) index, which records no org ownership, so the
    query engine can only ever read and cite the documents it is given.
    """

    def __init__(self, documents: list[Any], *, requested: bool = False) -> None:
        self._documents = documents
        self._requested = requested

    def rank(self, query: str, document_ids: list[str] | None = None) -> list[_DocumentHit]:
        terms = set(_WORD.findall(query.lower()))
        hits = []
        for doc in self._documents:
            if document_ids is not None and doc.id not in document_ids:
                continue
            words = set(_WORD.findall(doc.text.lower()))
            overlap = len(terms & words) / len(terms) if terms else 0.0
            hits.append(
                _DocumentHit(
                    document_id=doc.id,
                    filename=doc.filename,
                    content=doc.text[:_MAX_RESULT_CHARS],
                    # Documents the caller named are what the request is about.
                    combined_score=1.0 if self._requested else overlap,
                    keyword_score=overlap,
                )
            )
        hits.sort(key=lambda hit: hit.combined_score, reverse=True)
        return hits

    async def search(
        self,
        query: str,
        limit: int = 10,
        document_ids: list[str] | None = None,
        vector_weight: float | None = None,
    ) -> list[_DocumentHit]:
        return self.rank(query, document_ids)[:limit]


class DocumentQueryHandler(BaseHandler):
    """Handler for natural language document query endpoints."""

    def __init__(self, ctx: dict | None = None, server_context: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = server_context or ctx or {}

    ROUTES = [
        "/api/v1/documents/query",
        "/api/v1/documents/search",
        "/api/v1/documents/summarize",
        "/api/v1/documents/compare",
        "/api/v1/documents/extract",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        return path in self.ROUTES

    @require_permission("documents:read")
    def handle(self, path: str, query_params: dict, handler) -> HandlerResult | None:
        """Handle GET requests: search, or 405 for the POST-only query endpoints."""
        if path not in self.ROUTES:
            return None
        scope, scope_err = require_org_scope(handler)
        if scope is None:
            return scope_err
        if path == "/api/v1/documents/search":
            query = get_string_param(query_params, "q") or get_string_param(query_params, "query")
            limit = safe_query_int(query_params, "limit", default=20, min_val=1, max_val=100)
            offset = safe_query_int(query_params, "offset", default=0, min_val=0, max_val=10000)
            return self._search_documents(scope, query, limit, offset)
        return error_response(
            "Use POST method for document queries", 405, code="METHOD_NOT_ALLOWED"
        )

    @handle_errors("document query creation")
    @require_permission("documents:read")
    def handle_post(self, path: str, query_params: dict, handler) -> HandlerResult | None:
        """Route POST requests to appropriate methods."""
        if path not in self.ROUTES:
            return None
        scope, scope_err = require_org_scope(handler)
        if scope is None:
            return scope_err
        if path == "/api/v1/documents/query":
            return self._query_documents(handler, scope)
        elif path == "/api/v1/documents/search":
            body = self.read_json_body(handler) or {}
            query = body.get("query") or body.get("q") or ""
            limit = body.get("limit", 20)
            offset = body.get("offset", 0)
            if not isinstance(limit, int) or not isinstance(offset, int):
                return error_response("'limit' and 'offset' must be integers", 400)
            return self._search_documents(scope, query, min(max(limit, 1), 100), max(offset, 0))
        elif path == "/api/v1/documents/summarize":
            return self._summarize_documents(handler, scope)
        elif path == "/api/v1/documents/compare":
            return self._compare_documents(handler, scope)
        elif path == "/api/v1/documents/extract":
            return self._extract_information(handler, scope)
        return None

    def _org_documents(
        self, scope: OrgScope, document_ids: Any
    ) -> tuple[list[Any], HandlerResult | None]:
        """The caller org's documents: the requested ids, or all of them when None.

        Any requested id that is missing or not the caller org's answers 404.
        """
        store = self.ctx.get("document_store")
        if document_ids is None:
            if store is None:
                return [], None
            stored = (store.get(s["id"]) for s in store.list_for_org(scope.org_id))
            return [d for d in stored if d is not None], None
        if not isinstance(document_ids, list) or not all(
            isinstance(doc_id, str) for doc_id in document_ids
        ):
            return [], error_response("'document_ids' must be a list of strings", 400)
        docs = []
        for doc_id in dict.fromkeys(document_ids):
            doc = store.get(doc_id) if store is not None else None
            if doc is None or not record_visible(getattr(doc, "org_id", None), scope):
                return [], record_not_found("Document")
            docs.append(doc)
        return docs, None

    def _search_documents(
        self, scope: OrgScope, query: Any, limit: int, offset: int
    ) -> HandlerResult:
        """Keyword search over the caller org's documents."""
        if not isinstance(query, str) or not query.strip():
            return error_response("'q' (or 'query') is required", 400)
        docs, _ = self._org_documents(scope, None)
        matches = [hit for hit in _OrgDocumentSearcher(docs).rank(query) if hit.keyword_score > 0]
        page = matches[offset : offset + limit]
        return json_response(
            {
                "query": query,
                "results": [
                    {
                        "document_id": hit.document_id,
                        "filename": hit.filename,
                        "score": round(hit.keyword_score, 4),
                        "snippet": hit.content[:_SNIPPET_CHARS],
                    }
                    for hit in page
                ],
                "total": len(matches),
                "limit": limit,
                "offset": offset,
            }
        )

    @staticmethod
    async def _engine(config: QueryConfig, docs: list[Any], requested: bool) -> DocumentQueryEngine:
        return await DocumentQueryEngine.create(
            config=config, searcher=_OrgDocumentSearcher(docs, requested=requested)
        )

    @handle_errors("document query")
    def _query_documents(self, handler, scope: OrgScope) -> HandlerResult:
        """
        Answer a natural language question about documents.

        Request body:
        {
            "question": "What are the payment terms?",
            "document_ids": ["doc1", "doc2"],  // Optional: scope to specific docs
            "workspace_id": "ws_123",  // Optional
            "conversation_id": "conv_123",  // Optional: for multi-turn
            "config": {  // Optional
                "max_chunks": 10,
                "include_quotes": true
            }
        }

        Response:
        {
            "query_id": "query_abc123",
            "question": "...",
            "answer": "...",
            "confidence": "high",
            "citations": [...],
            "processing_time_ms": 1234
        }
        """
        body = self.read_json_body(handler)
        if not body:
            return error_response("Request body required", 400)

        document_ids = body.get("document_ids")
        docs, err = self._org_documents(scope, document_ids)
        if err:
            return err

        question = body.get("question", "").strip()
        if not question:
            return error_response("'question' field is required", 400)

        workspace_id = body.get("workspace_id")
        conversation_id = body.get("conversation_id")
        config_dict = body.get("config", {})

        # Run async query
        try:
            result = _run_async(
                self._run_query(
                    question=question,
                    document_ids=[doc.id for doc in docs],
                    workspace_id=workspace_id,
                    conversation_id=conversation_id,
                    config_dict=config_dict,
                    docs=docs,
                    requested=document_ids is not None,
                )
            )
            return json_response(result)
        except (RuntimeError, ValueError, TypeError, OSError, KeyError) as e:
            logger.error("Query failed: %s", e)
            return error_response(safe_error_message(e, "Query"), 500)

    async def _run_query(
        self,
        question: str,
        document_ids: list[str] | None,
        workspace_id: str | None,
        conversation_id: str | None,
        config_dict: dict,
        docs: list[Any] | None = None,
        requested: bool = False,
    ) -> dict[str, Any]:
        """Run the document query asynchronously."""
        # Build config from request
        config = QueryConfig(
            max_chunks=config_dict.get("max_chunks", 10),
            include_quotes=config_dict.get("include_quotes", True),
            max_answer_length=config_dict.get("max_answer_length", 500),
        )

        engine = await self._engine(config, docs or [], requested)
        result = await engine.query(
            question=question,
            workspace_id=workspace_id,
            document_ids=document_ids,
            conversation_id=conversation_id,
        )

        return result.to_dict()

    @handle_errors("document summarize")
    def _summarize_documents(self, handler, scope: OrgScope) -> HandlerResult:
        """
        Summarize one or more documents.

        Request body:
        {
            "document_ids": ["doc1", "doc2"],
            "focus": "financial terms",  // Optional: focus area
            "config": {...}  // Optional
        }

        Response:
        {
            "query_id": "...",
            "answer": "Summary...",
            "confidence": "high",
            "citations": [...]
        }
        """
        body = self.read_json_body(handler)
        if not body:
            return error_response("Request body required", 400)

        document_ids = body.get("document_ids", [])
        if not document_ids:
            return error_response("'document_ids' field is required", 400)

        focus = body.get("focus")
        config_dict = body.get("config", {})

        docs, err = self._org_documents(scope, document_ids)
        if err:
            return err

        try:
            result = _run_async(
                self._run_summarize(
                    document_ids=[doc.id for doc in docs],
                    focus=focus,
                    config_dict=config_dict,
                    docs=docs,
                )
            )
            return json_response(result)
        except (RuntimeError, ValueError, TypeError, OSError, KeyError) as e:
            logger.error("Summarize failed: %s", e)
            return error_response(safe_error_message(e, "Summarize"), 500)

    async def _run_summarize(
        self,
        document_ids: list[str],
        focus: str | None,
        config_dict: dict,
        docs: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Run document summarization asynchronously."""
        config = QueryConfig(
            **{k: v for k, v in config_dict.items() if k in QueryConfig.__annotations__}
        )
        engine = await self._engine(config, docs or [], requested=True)
        result = await engine.summarize_documents(
            document_ids=document_ids,
            focus=focus,
        )

        return result.to_dict()

    @handle_errors("document compare")
    def _compare_documents(self, handler, scope: OrgScope) -> HandlerResult:
        """
        Compare multiple documents.

        Request body:
        {
            "document_ids": ["doc1", "doc2"],  // At least 2
            "aspects": ["pricing", "terms"],  // Optional: specific aspects
            "config": {...}
        }

        Response:
        {
            "query_id": "...",
            "answer": "Comparison...",
            "confidence": "high",
            "citations": [...]
        }
        """
        body = self.read_json_body(handler)
        if not body:
            return error_response("Request body required", 400)

        docs, err = self._org_documents(scope, body.get("document_ids") or [])
        if err:
            return err
        if len(docs) < 2:
            return error_response("At least 2 document_ids required for comparison", 400)

        aspects = body.get("aspects")
        config_dict = body.get("config", {})

        try:
            result = _run_async(
                self._run_compare(
                    document_ids=[doc.id for doc in docs],
                    aspects=aspects,
                    config_dict=config_dict,
                    docs=docs,
                )
            )
            return json_response(result)
        except (RuntimeError, ValueError, TypeError, OSError, KeyError) as e:
            logger.error("Compare failed: %s", e)
            return error_response(safe_error_message(e, "Compare"), 500)

    async def _run_compare(
        self,
        document_ids: list[str],
        aspects: list[str] | None,
        config_dict: dict,
        docs: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Run document comparison asynchronously."""
        config = QueryConfig(
            **{k: v for k, v in config_dict.items() if k in QueryConfig.__annotations__}
        )
        engine = await self._engine(config, docs or [], requested=True)
        result = await engine.compare_documents(
            document_ids=document_ids,
            aspects=aspects,
        )

        return result.to_dict()

    @handle_errors("document extract")
    def _extract_information(self, handler, scope: OrgScope) -> HandlerResult:
        """
        Extract structured information from documents.

        Request body:
        {
            "document_ids": ["doc1"],
            "fields": {
                "parties": "Who are the parties to this agreement?",
                "effective_date": "What is the effective date?",
                "term": "What is the term or duration?",
                "payment_terms": "What are the payment terms?"
            },
            "config": {...}
        }

        Response:
        {
            "document_ids": ["doc1"],
            "extractions": {
                "parties": {"answer": "...", "confidence": "high", "citations": [...]},
                "effective_date": {...},
                ...
            }
        }
        """
        body = self.read_json_body(handler)
        if not body:
            return error_response("Request body required", 400)

        document_ids = body.get("document_ids", [])
        if not document_ids:
            return error_response("'document_ids' field is required", 400)

        docs, err = self._org_documents(scope, document_ids)
        if err:
            return err

        fields = body.get("fields", {})
        if not fields:
            return error_response("'fields' dict is required with extraction queries", 400)

        config_dict = body.get("config", {})

        try:
            result = _run_async(
                self._run_extract(
                    document_ids=[doc.id for doc in docs],
                    fields=fields,
                    config_dict=config_dict,
                    docs=docs,
                )
            )
            return json_response(result)
        except (RuntimeError, ValueError, TypeError, OSError, KeyError) as e:
            logger.error("Extract failed: %s", e)
            return error_response(safe_error_message(e, "Extract"), 500)

    async def _run_extract(
        self,
        document_ids: list[str],
        fields: dict[str, str],
        config_dict: dict,
        docs: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Run structured extraction asynchronously."""
        config = QueryConfig(
            **{k: v for k, v in config_dict.items() if k in QueryConfig.__annotations__}
        )
        engine = await self._engine(config, docs or [], requested=True)
        results = await engine.extract_information(
            document_ids=document_ids,
            extraction_template=fields,
        )

        return {
            "document_ids": document_ids,
            "extractions": {field: result.to_dict() for field, result in results.items()},
        }
