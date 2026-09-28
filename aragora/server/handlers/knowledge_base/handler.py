"""
Main Knowledge Handler.

Combines all mixins to provide the complete Knowledge Base API:

Facts API (FactStore):
- POST /api/knowledge/query - Natural language query against dataset
- GET /api/knowledge/facts - List facts with filtering
- GET /api/knowledge/facts/:id - Get specific fact
- POST /api/knowledge/facts - Add a new fact
- PUT /api/knowledge/facts/:id - Update a fact
- DELETE /api/knowledge/facts/:id - Delete a fact
- POST /api/knowledge/facts/:id/verify - Verify fact with agents
- GET /api/knowledge/facts/:id/contradictions - Get contradicting facts
- GET /api/knowledge/facts/:id/relations - Get fact relations
- POST /api/knowledge/facts/relations - Add relation between facts
- GET /api/knowledge/search - Search chunks via embeddings
- GET /api/knowledge/stats - Get knowledge base statistics

Index API (no named-index registry exists yet):
- POST /api/v1/index/embed-batch - Embed texts with the unified embedding service
- GET /api/v1/index - List named vector indexes (always empty)
- POST /api/v1/index, POST /api/v1/index/search - 501 not_implemented
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from aragora.core.embeddings.types import EmbeddingError
from aragora.knowledge import (
    DatasetQueryEngine,
    FactStore,
    InMemoryEmbeddingService,
    InMemoryFactStore,
    SimpleQueryEngine,
)
from aragora.rbac.decorators import require_permission
from aragora.server.http_utils import run_async as _run_async

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    get_bounded_string_param,
    json_response,
)
from ..utils.rate_limit import RateLimiter, get_client_ip

from .facts import FactsOperationsMixin
from .query import QueryOperationsMixin
from .search import SearchOperationsMixin

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Rate limiter for knowledge endpoints (60 requests per minute)
_knowledge_limiter = RateLimiter(requests_per_minute=60)

# Allowed methods per /api/v1/index route (also the 405 Allow header).
_INDEX_ROUTE_METHODS = {
    "/api/v1/index": "GET, POST",
    "/api/v1/index/embed-batch": "POST",
    "/api/v1/index/search": "POST",
}
_MAX_EMBED_BATCH_TEXTS = 1000
_MAX_EMBED_BATCH_SIZE = 100
# Shared by every backend call of one embed-batch request, so small batch sizes
# cannot turn one request into many sequential 30 s waits.
_EMBED_BATCH_BUDGET_SECONDS = 30.0
_NOT_IMPLEMENTED_MESSAGE = "Named vector indexes are not implemented on this server"


class KnowledgeHandler(
    FactsOperationsMixin,
    QueryOperationsMixin,
    SearchOperationsMixin,
    BaseHandler,
):
    """Handler for knowledge base API endpoints.

    Combines mixins for:
    - Fact CRUD operations (FactsOperationsMixin)
    - Natural language queries (QueryOperationsMixin)
    - Search and statistics (SearchOperationsMixin)
    """

    # RBAC permission keys
    KNOWLEDGE_READ_PERMISSION = "knowledge.read"
    KNOWLEDGE_WRITE_PERMISSION = "knowledge.write"
    KNOWLEDGE_DELETE_PERMISSION = "knowledge.delete"

    ROUTES = [
        "/api/v1/knowledge/query",
        "/api/v1/knowledge/facts",
        "/api/v1/knowledge/facts/relations",
        "/api/v1/knowledge/facts/*",
        "/api/v1/knowledge/facts/*/verify",
        "/api/v1/knowledge/facts/*/contradictions",
        "/api/v1/knowledge/facts/*/relations",
        "/api/v1/knowledge/search",
        "/api/v1/knowledge/stats",
        "/api/v1/knowledge/embeddings",
        "/api/v1/knowledge/entries/*/embeddings",
        "/api/v1/knowledge/entries/*/sources",
        "/api/v1/knowledge/export",
        "/api/v1/knowledge/refresh",
        "/api/v1/knowledge/validate",
        # Aliases: SDK expects /api/v1/facts/* without the /knowledge/ prefix
        "/api/v1/facts",
        "/api/v1/facts/batch",
        "/api/v1/facts/batch/delete",
        "/api/v1/facts/merge",
        "/api/v1/facts/relationships",
        "/api/v1/facts/stats",
        "/api/v1/facts/validate",
        # Index/embedding routes
        "/api/v1/index",
        "/api/v1/index/embed-batch",
        "/api/v1/index/search",
    ]

    def __init__(self, server_context: dict[str, Any]):
        """Initialize knowledge handler.

        Args:
            server_context: Server context with shared resources
        """
        super().__init__(server_context)
        # Reset global limiter buckets to avoid cross-test leakage.
        try:
            _knowledge_limiter._buckets.clear()
        except (AttributeError, TypeError):
            logger.debug("Failed to clear knowledge limiter buckets", exc_info=True)
        self._fact_store: FactStore | InMemoryFactStore | None = None
        self._query_engine: DatasetQueryEngine | SimpleQueryEngine | None = None
        self._knowledge_mound: Any | None = None

    def _get_fact_store(self) -> FactStore | InMemoryFactStore:
        """Get or create fact store."""
        if self._fact_store is None:
            try:
                self._fact_store = FactStore()
            except (OSError, ValueError, TypeError, RuntimeError, ImportError) as e:
                logger.warning("Failed to create FactStore, using in-memory: %s", e)
                self._fact_store = InMemoryFactStore()
        return self._fact_store

    def _get_query_engine(self) -> DatasetQueryEngine | SimpleQueryEngine:
        """Get or create query engine."""
        if self._query_engine is None:
            fact_store = self._get_fact_store()
            embedding_service = InMemoryEmbeddingService()
            self._query_engine = SimpleQueryEngine(
                fact_store=fact_store,
                embedding_service=embedding_service,
            )
        return self._query_engine

    def _get_knowledge_mound(self) -> Any | None:
        """Get an explicitly configured Knowledge Mound instance when available."""
        mound = self.ctx.get("knowledge_mound")
        if mound is not None:
            return mound
        return self._knowledge_mound

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        if path in self.ROUTES:
            return True
        if path.startswith("/api/v1/knowledge/facts/"):
            return True
        # Alias: SDK expects /api/v1/facts/* without the /knowledge/ prefix
        if path.startswith("/api/v1/facts/"):
            return True
        return False

    @staticmethod
    def _normalize_facts_path(path: str) -> str:
        """Normalize /api/v1/facts/* to /api/v1/knowledge/facts/* for routing.

        The SDK uses the shorter /api/v1/facts/ prefix, but the internal
        routing logic expects the canonical /api/v1/knowledge/facts/ prefix.
        """
        if path == "/api/v1/facts" or path.startswith("/api/v1/facts/"):
            return path.replace("/api/v1/facts", "/api/v1/knowledge/facts", 1)
        return path

    def _check_permission(self, handler: Any, permission: str) -> HandlerResult | None:
        """Check RBAC permission and return error response if denied."""
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        # Check permission
        permissions = getattr(user, "permissions", []) or []
        roles = getattr(user, "roles", []) or []
        if permission not in permissions and "admin" not in roles and "admin" not in permissions:
            return error_response("Permission denied", 403)
        return None

    @require_permission("knowledge:read")
    def handle(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route knowledge requests to appropriate methods."""
        # Normalize /api/v1/facts/* aliases to canonical /api/v1/knowledge/facts/*
        path = self._normalize_facts_path(path)

        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _knowledge_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for knowledge endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        # Check read permission for GET requests
        method = getattr(handler, "command", "GET")
        if method == "GET":
            perm_error = self._check_permission(handler, self.KNOWLEDGE_READ_PERMISSION)
            if perm_error:
                return perm_error
        elif method == "POST":
            # Query and index search are reads; every other POST is a write
            if path in ("/api/v1/knowledge/query", "/api/v1/index/search"):
                perm_error = self._check_permission(handler, self.KNOWLEDGE_READ_PERMISSION)
            else:
                perm_error = self._check_permission(handler, self.KNOWLEDGE_WRITE_PERMISSION)
            if perm_error:
                return perm_error
        elif method == "PUT":
            perm_error = self._check_permission(handler, self.KNOWLEDGE_WRITE_PERMISSION)
            if perm_error:
                return perm_error
        elif method == "DELETE":
            perm_error = self._check_permission(handler, self.KNOWLEDGE_DELETE_PERMISSION)
            if perm_error:
                return perm_error

        if path in _INDEX_ROUTE_METHODS:
            return self._handle_index_routes(path, method, handler)

        # Query endpoint (POST)
        if path == "/api/v1/knowledge/query":
            return self._handle_query(query_params, handler)

        # Facts listing (GET) or creation (POST)
        if path == "/api/v1/knowledge/facts":
            method = getattr(handler, "command", "GET")
            if method == "POST":
                return self._handle_create_fact(handler)
            return self._handle_list_facts(query_params)

        # Search chunks
        if path == "/api/v1/knowledge/search":
            return self._handle_search(query_params)

        # Statistics
        if path == "/api/v1/knowledge/stats":
            workspace_id = get_bounded_string_param(
                query_params, "workspace_id", None, max_length=100
            )
            return self._handle_stats(workspace_id)

        # Dynamic fact routes
        if path.startswith("/api/v1/knowledge/facts/"):
            return self._handle_fact_routes(path, query_params, handler)

        return None

    def _handle_index_routes(self, path: str, method: str, handler: Any) -> HandlerResult:
        """Handle the /api/v1/index family; there is no named-index registry yet."""
        if method not in _INDEX_ROUTE_METHODS[path].split(", "):
            return error_response(
                "Method not allowed", 405, headers={"Allow": _INDEX_ROUTE_METHODS[path]}
            )
        if path == "/api/v1/index/embed-batch":
            return self._handle_embed_batch(handler)
        if method == "GET":
            return json_response({"indexes": [], "count": 0})
        # The error_response(..., code=...) envelope, built directly because
        # error_response replaces every 5xx message in production.
        return json_response(
            {"error": {"message": _NOT_IMPLEMENTED_MESSAGE, "code": "not_implemented"}},
            status=501,
        )

    def _handle_embed_batch(self, handler: Any) -> HandlerResult:
        """Handle POST /api/v1/index/embed-batch with the unified embedding service."""
        data = self.read_json_body(handler)
        if data is None:
            return error_response("Invalid JSON body", 400)
        texts = data.get("texts")
        if not isinstance(texts, list) or not texts or not all(isinstance(t, str) for t in texts):
            return error_response("'texts' must be a non-empty list of strings", 400)
        if len(texts) > _MAX_EMBED_BATCH_TEXTS:
            return error_response(f"At most {_MAX_EMBED_BATCH_TEXTS} texts per request", 400)
        batch_size = data.get("batch_size", _MAX_EMBED_BATCH_SIZE)
        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or not 1 <= batch_size <= _MAX_EMBED_BATCH_SIZE
        ):
            return error_response(
                f"'batch_size' must be an integer from 1 to {_MAX_EMBED_BATCH_SIZE}", 400
            )

        from aragora.core.embeddings.service import get_embedding_service

        try:
            service = get_embedding_service()
            requested_model = data.get("model")
            if requested_model is not None and requested_model != service.model:
                return error_response(
                    f"Model selection is not supported; this server embeds with {service.model}",
                    400,
                )
            batches = [texts[i : i + batch_size] for i in range(0, len(texts), batch_size)]
            embeddings: list[list[float]] = []
            deadline = time.monotonic() + _EMBED_BATCH_BUDGET_SECONDS
            for batch in batches:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"embed-batch exceeded its {_EMBED_BATCH_BUDGET_SECONDS:g}s budget"
                    )
                vectors = _run_async(service.embed_batch_raw(batch), timeout=remaining)
                if len(vectors) != len(batch):
                    raise ValueError(f"backend returned {len(vectors)} vectors for {len(batch)}")
                embeddings.extend(vectors)
        # AttributeError/TypeError: UnifiedEmbeddingService.embed_batch leaves None
        # placeholders when a backend returns fewer vectors than it was given.
        except (
            EmbeddingError,
            RuntimeError,
            OSError,
            TimeoutError,
            ValueError,
            AttributeError,
            TypeError,
        ) as e:
            logger.warning("Index embed-batch failed: %s", e)
            return error_response("Embedding service unavailable", 503)

        return json_response(
            {
                "embeddings": embeddings,
                "dimension": len(embeddings[0]) if embeddings else 0,
                "count": len(embeddings),
                "batch_count": len(batches),
                "provider": service.provider,
                "model": service.model,
            }
        )

    def _handle_fact_routes(
        self, path: str, query_params: dict, handler: Any
    ) -> HandlerResult | None:
        """Handle /api/v1/knowledge/facts/:id/* routes."""
        parts = path.strip("/").split("/")

        # /api/v1/knowledge/facts/:id (5 parts: api, v1, knowledge, facts, id)
        if len(parts) == 5:
            fact_id = parts[4]
            method = getattr(handler, "command", "GET")
            if method == "GET":
                return self._handle_get_fact(fact_id)
            elif method == "PUT":
                return self._handle_update_fact(fact_id, handler)
            elif method == "DELETE":
                return self._handle_delete_fact(fact_id, handler)

        # /api/v1/knowledge/facts/:id/verify (6 parts)
        if len(parts) == 6 and parts[5] == "verify":
            fact_id = parts[4]
            return self._handle_verify_fact(fact_id, handler)

        # /api/v1/knowledge/facts/:id/contradictions (6 parts)
        if len(parts) == 6 and parts[5] == "contradictions":
            fact_id = parts[4]
            return self._handle_get_contradictions(fact_id)

        # /api/v1/knowledge/facts/:id/relations (6 parts)
        if len(parts) == 6 and parts[5] == "relations":
            fact_id = parts[4]
            method = getattr(handler, "command", "GET")
            if method == "POST":
                return self._handle_add_relation(fact_id, handler)
            return self._handle_get_relations(fact_id, query_params)

        # /api/v1/knowledge/facts/relations (POST - add relation) (5 parts)
        if len(parts) == 5 and parts[4] == "relations":
            return self._handle_add_relation_bulk(handler)

        return error_response("Unknown endpoint", 404)
