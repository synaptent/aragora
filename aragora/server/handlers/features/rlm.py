"""
RLM (Recursive Language Model) endpoint handlers.

Stability: STABLE

Endpoints:
- POST /api/debates/{id}/query-rlm - Query a debate using RLM with refinement
- POST /api/debates/{id}/compress - Compress debate context using RLM
- GET /api/debates/{id}/context/{level} - Get debate at specific abstraction level
- GET /api/debates/{id}/refinement-status - Check iterative refinement progress
- POST /api/knowledge/query-rlm - Query knowledge mound using RLM

Security:
    All endpoints require RBAC permissions:
    - debates.read: Query and compress debate context
    - knowledge.read: Query knowledge mound
    - analytics.read: Access RLM metrics

Features:
    - Circuit breaker pattern for resilient RLM operations
    - Rate limiting (30 requests/minute for queries, 60/minute for status)
    - RBAC permission checks
    - Input validation with size limits
    - Comprehensive error handling with safe error messages
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from aragora.server.http_utils import run_async as _run_async
from aragora.rbac.checker import get_permission_checker
from aragora.rbac.models import AuthorizationContext

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
    require_user_auth,
    safe_error_message,
)
from ..utils.decorators import require_permission
from ..utils.rate_limit import rate_limit

logger = logging.getLogger(__name__)


# =============================================================================
# Circuit Breaker for RLM Operations
# =============================================================================

from aragora.resilience.simple_circuit_breaker import SimpleCircuitBreaker as RLMCircuitBreaker


# Global circuit breakers for RLM operations
_rlm_circuit_breakers: dict[str, RLMCircuitBreaker] = {}
_circuit_breaker_lock = threading.Lock()


def _get_rlm_circuit_breaker(operation: str) -> RLMCircuitBreaker:
    """Get or create a circuit breaker for an RLM operation."""
    with _circuit_breaker_lock:
        if operation not in _rlm_circuit_breakers:
            _rlm_circuit_breakers[operation] = RLMCircuitBreaker()
        return _rlm_circuit_breakers[operation]


def get_rlm_circuit_breaker_status() -> dict[str, Any]:
    """Get status of all RLM circuit breakers."""
    with _circuit_breaker_lock:
        return {name: breaker.get_status() for name, breaker in _rlm_circuit_breakers.items()}


def _clear_rlm_circuit_breakers() -> None:
    """Clear all circuit breakers (for testing)."""
    with _circuit_breaker_lock:
        _rlm_circuit_breakers.clear()


class RLMHandler(BaseHandler):
    """Handler for RLM-powered query and compression endpoints.

    RBAC Permissions:
    - debates.read: Query and compress debate context
    - knowledge.read: Query knowledge mound
    - analytics.read: Access RLM metrics
    """

    def __init__(self, ctx: dict | None = None, server_context: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = server_context or ctx or {}

    RESOURCE_TYPE = "rlm"  # For audit logging

    ROUTES = [
        "/api/v1/debates/{debate_id}/query-rlm",
        "/api/v1/debates/{debate_id}/compress",
        "/api/v1/debates/{debate_id}/context/{level}",
        "/api/v1/debates/{debate_id}/refinement-status",
        "/api/v1/knowledge/query-rlm",
        "/api/v1/rlm/status",
        "/api/v1/rlm/codebase/health",
        "/api/v1/rlm/compress",
        "/api/v1/rlm/contexts",
        "/api/v1/rlm/query",
        "/api/v1/rlm/stats",
        "/api/v1/rlm/strategies",
        "/api/v1/rlm/stream",
        "/api/v1/rlm/stream/modes",
        "/api/v1/metrics/rlm",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        # Handle parameterized routes
        if path.startswith("/api/v1/debates/") and "/query-rlm" in path:
            return True
        if path.startswith("/api/v1/debates/") and "/compress" in path:
            return True
        if path.startswith("/api/v1/debates/") and "/context/" in path:
            return True
        if path.startswith("/api/v1/debates/") and "/refinement-status" in path:
            return True
        if path == "/api/v1/knowledge/query-rlm":
            return True
        if path == "/api/v1/rlm/status":
            return True
        if path == "/api/v1/metrics/rlm":
            return True
        return False

    def _extract_debate_id(self, path: str) -> str | None:
        """Extract debate ID from path like /api/v1/debates/{id}/..."""
        parts = path.split("/")
        # Path: /api/v1/debates/{id}/... - debate_id at index 4
        if len(parts) >= 5 and parts[1] == "api" and parts[2] == "v1" and parts[3] == "debates":
            return parts[4]
        return None

    def _extract_level(self, path: str) -> str | None:
        """Extract abstraction level from path like /api/v1/debates/{id}/context/{level}."""
        parts = path.split("/")
        # Path: /api/v1/debates/{id}/context/{level} - context at index 5, level at index 6
        if len(parts) >= 7 and parts[5] == "context":
            return parts[6].upper()
        return None

    def _check_permission(self, user, permission: str) -> HandlerResult | None:
        """Check RBAC permission for the authenticated user.

        Returns None if permission is granted, or an error response if denied.
        """
        if not user:
            return error_response("Authentication required", 401)

        try:
            auth_context = AuthorizationContext(
                user_id=getattr(user, "user_id", "anonymous"),
                org_id=getattr(user, "org_id", None),
                roles=getattr(user, "roles", {"member"}),
            )

            checker = get_permission_checker()
            decision = checker.check_permission(auth_context, permission)

            if not decision.allowed:
                logger.warning("Permission denied: %s", permission)
                return error_response("Permission denied", 403)
            return None
        except (TypeError, ValueError, KeyError, AttributeError) as e:
            logger.error("RBAC check failed: %s", e)
            return error_response("Authorization check failed", 500)

    def handle(self, path: str, query_params: dict, handler) -> HandlerResult | None:
        """Handle GET requests."""
        if path == "/api/v1/rlm/status":
            return self._get_rlm_status()
        if path == "/api/v1/metrics/rlm":
            return self._get_rlm_metrics()
        if "/context/" in path:
            return self._get_context_level(path, handler)
        if "/refinement-status" in path:
            return self._get_refinement_status(path, handler)
        return error_response("Use POST method for RLM queries", 405)

    @handle_errors("r l m creation")
    @require_permission("debates:write")
    def handle_post(self, path: str, query_params: dict, handler) -> HandlerResult | None:
        """Route POST requests to appropriate methods."""
        if "/query-rlm" in path and path.startswith("/api/v1/debates/"):
            return self._query_debate_rlm(path, handler)
        if "/compress" in path:
            return self._compress_debate(path, handler)
        if path == "/api/v1/knowledge/query-rlm":
            return self._query_knowledge_rlm(handler)
        return None

    @rate_limit(requests_per_minute=30, limiter_name="rlm_query")
    @require_user_auth
    @handle_errors("RLM debate query")
    def _query_debate_rlm(self, path: str, handler, user=None) -> HandlerResult:
        """
        Query a debate using RLM with iterative refinement.

        Rate limited to 30 requests per minute.

        Request body:
        {
            "query": "What was the consensus on pricing?",
            "strategy": "auto",  // Optional: auto, peek, grep, partition_map
            "max_iterations": 3,  // Optional: max refinement iterations
            "start_level": "SUMMARY"  // Optional: starting abstraction level
        }

        Response:
        {
            "answer": "The debate reached consensus that...",
            "ready": true,
            "iteration": 1,
            "refinement_history": [...],
            "confidence": 0.85,
            "nodes_examined": [...],
            "tokens_processed": 5000
        }
        """
        # RBAC check
        rbac_error = self._check_permission(user, "debates.read")
        if rbac_error:
            return rbac_error

        debate_id = self._extract_debate_id(path)
        if not debate_id:
            return error_response("Invalid debate ID", 400)

        # Validate debate_id format
        if len(debate_id) > 100 or not debate_id.replace("-", "").replace("_", "").isalnum():
            return error_response("Invalid debate ID format", 400)

        body = handler.get_json_body()
        if not body:
            return error_response("Request body required", 400)

        query = body.get("query")
        if not query:
            return error_response("Query is required", 400)

        # Validate query length
        if len(query) > 10000:
            return error_response("Query too long (max 10000 characters)", 400)

        strategy = body.get("strategy", "auto")
        valid_strategies = ["auto", "peek", "grep", "partition_map", "summarize", "hierarchical"]
        if strategy not in valid_strategies:
            return error_response(
                f"Invalid strategy. Must be one of: {', '.join(valid_strategies)}", 400
            )

        max_iterations = body.get("max_iterations", 3)
        if not isinstance(max_iterations, int) or max_iterations < 1 or max_iterations > 10:
            max_iterations = 3

        start_level = body.get("start_level", "SUMMARY")
        valid_levels = ["ABSTRACT", "SUMMARY", "DETAILED", "RAW"]
        if start_level.upper() not in valid_levels:
            return error_response(
                f"Invalid start_level. Must be one of: {', '.join(valid_levels)}", 400
            )

        # Check circuit breaker
        circuit_breaker = _get_rlm_circuit_breaker("query")
        if not circuit_breaker.can_proceed():
            logger.warning("RLM query circuit breaker is open")
            return error_response(
                "RLM service temporarily unavailable. Please try again later.",
                503,
            )

        try:
            result = _run_async(
                self._execute_rlm_query(
                    debate_id=debate_id,
                    query=query,
                    strategy=strategy,
                    max_iterations=max_iterations,
                    start_level=start_level,
                )
            )

            circuit_breaker.record_success()

            return json_response(
                {
                    "answer": result.answer,
                    "ready": result.ready,
                    "iteration": result.iteration,
                    "refinement_history": result.refinement_history,
                    "confidence": result.confidence,
                    "nodes_examined": result.nodes_examined,
                    "tokens_processed": result.tokens_processed,
                    "sub_calls_made": result.sub_calls_made,
                }
            )

        except (RuntimeError, ValueError, OSError, TimeoutError, AttributeError) as e:
            circuit_breaker.record_failure()
            logger.error("RLM query failed: %s", e)
            return error_response(safe_error_message(e, "RLM query"), 500)

    async def _execute_rlm_query(
        self,
        debate_id: str,
        query: str,
        strategy: str,
        max_iterations: int,
        start_level: str,
    ) -> Any:
        """Execute RLM query with refinement loop."""
        from aragora.rlm.bridge import AragoraRLM, DebateContextAdapter

        # Get debate result
        debate_result = await self._get_debate_result(debate_id)
        if not debate_result:
            raise ValueError(f"Debate {debate_id} not found")

        # Create RLM instance
        rlm = AragoraRLM()

        # Create adapter and compress debate
        adapter = DebateContextAdapter(rlm)
        context = await adapter.compress_debate(debate_result)

        # Execute query with refinement
        result = await rlm.query_with_refinement(
            query=query,
            context=context,
            strategy=strategy,
            max_iterations=max_iterations,
            start_level=start_level,
        )

        return result

    async def _get_debate_result(self, debate_id: str) -> dict[str, Any] | None:
        """Fetch debate result from storage.

        Attempts to retrieve debate data from the available storage backend.
        Falls back gracefully if storage is not configured.
        """
        try:
            from aragora.storage.postgres_store import get_postgres_pool
            from aragora.server.postgres_storage import PostgresDebateStorage

            pool = await get_postgres_pool()
            if pool is None:
                logger.warning("No database pool available for debate %s", debate_id)
                return None

            store = PostgresDebateStorage(pool)
            await store.initialize()
            return await store.get_by_id_async(debate_id)
        except ImportError:
            logger.warning("PostgresDebateStorage not available for debate %s", debate_id)
            return None
        except (RuntimeError, ValueError, OSError, TimeoutError, KeyError) as e:
            logger.warning("Failed to get debate %s: %s", debate_id, e)
            return None

    @rate_limit(requests_per_minute=20, limiter_name="rlm_compress")
    @require_user_auth
    @handle_errors("RLM compression")
    def _compress_debate(self, path: str, handler, user=None) -> HandlerResult:
        """
        Compress a debate into hierarchical context.

        Rate limited to 20 requests per minute (compute-intensive).

        Request body:
        {
            "target_levels": ["ABSTRACT", "SUMMARY", "DETAILED"],  // Optional
            "compression_ratio": 0.3  // Optional: target compression
        }

        Response:
        {
            "original_tokens": 50000,
            "compressed_tokens": {
                "ABSTRACT": 500,
                "SUMMARY": 2500,
                "DETAILED": 10000
            },
            "compression_ratios": {...},
            "time_seconds": 2.5,
            "levels_created": 3
        }
        """
        # RBAC check
        rbac_error = self._check_permission(user, "debates.read")
        if rbac_error:
            return rbac_error

        debate_id = self._extract_debate_id(path)
        if not debate_id:
            return error_response("Invalid debate ID", 400)

        # Validate debate_id format
        if len(debate_id) > 100 or not debate_id.replace("-", "").replace("_", "").isalnum():
            return error_response("Invalid debate ID format", 400)

        body = handler.get_json_body() or {}
        target_levels = body.get("target_levels", ["ABSTRACT", "SUMMARY", "DETAILED"])

        # Validate target_levels
        valid_levels = ["ABSTRACT", "SUMMARY", "DETAILED", "RAW"]
        if not isinstance(target_levels, list):
            return error_response("target_levels must be a list", 400)
        for level in target_levels:
            if level.upper() not in valid_levels:
                return error_response(
                    f"Invalid level: {level}. Must be one of: {', '.join(valid_levels)}", 400
                )

        compression_ratio = body.get("compression_ratio", 0.3)
        if (
            not isinstance(compression_ratio, (int, float))
            or compression_ratio <= 0
            or compression_ratio > 1
        ):
            compression_ratio = 0.3

        # Check circuit breaker
        circuit_breaker = _get_rlm_circuit_breaker("compress")
        if not circuit_breaker.can_proceed():
            logger.warning("RLM compression circuit breaker is open")
            return error_response(
                "RLM service temporarily unavailable. Please try again later.",
                503,
            )

        try:
            result = _run_async(
                self._execute_compression(
                    debate_id=debate_id,
                    target_levels=target_levels,
                    compression_ratio=compression_ratio,
                )
            )
            circuit_breaker.record_success()
            return json_response(result)

        except (RuntimeError, ValueError, OSError, TimeoutError, AttributeError) as e:
            circuit_breaker.record_failure()
            logger.error("RLM compression failed: %s", e)
            return error_response(safe_error_message(e, "Compression"), 500)

    async def _execute_compression(
        self,
        debate_id: str,
        target_levels: list,
        compression_ratio: float,
    ) -> dict:
        """Execute debate compression."""
        from aragora.rlm.bridge import DebateContextAdapter
        from aragora.rlm.types import AbstractionLevel

        start_time = time.time()

        debate_result = await self._get_debate_result(debate_id)
        if not debate_result:
            raise ValueError(f"Debate {debate_id} not found")

        adapter = DebateContextAdapter()
        context = await adapter.compress_debate(debate_result)

        compressed_tokens = {}
        compression_ratios = {}

        for level_name in target_levels:
            try:
                level = AbstractionLevel[level_name]
                tokens = context.total_tokens_at_level(level)
                compressed_tokens[level_name] = tokens
                if context.original_tokens > 0:
                    compression_ratios[level_name] = tokens / context.original_tokens
            except KeyError:
                continue

        return {
            "original_tokens": context.original_tokens,
            "compressed_tokens": compressed_tokens,
            "compression_ratios": compression_ratios,
            "time_seconds": time.time() - start_time,
            "levels_created": len(context.levels),
        }

    @rate_limit(requests_per_minute=60, limiter_name="rlm_context")
    @require_user_auth
    @handle_errors("get context level")
    def _get_context_level(self, path: str, handler, user=None) -> HandlerResult:
        """
        Get debate content at a specific abstraction level.

        Rate limited to 60 requests per minute.

        Response:
        {
            "level": "SUMMARY",
            "content": "...",
            "token_count": 2500,
            "nodes": [...]
        }
        """
        # RBAC check
        rbac_error = self._check_permission(user, "debates.read")
        if rbac_error:
            return rbac_error

        debate_id = self._extract_debate_id(path)
        level_name = self._extract_level(path)

        if not debate_id:
            return error_response("Invalid debate ID", 400)

        # Validate debate_id format
        if len(debate_id) > 100 or not debate_id.replace("-", "").replace("_", "").isalnum():
            return error_response("Invalid debate ID format", 400)

        if not level_name:
            return error_response("Invalid abstraction level", 400)

        # Validate level_name
        valid_levels = ["ABSTRACT", "SUMMARY", "DETAILED", "RAW"]
        if level_name.upper() not in valid_levels:
            return error_response(f"Invalid level. Must be one of: {', '.join(valid_levels)}", 400)

        try:
            result = _run_async(self._get_level_content(debate_id, level_name))
            return json_response(result)
        except (RuntimeError, ValueError, OSError, TimeoutError, AttributeError) as e:
            logger.error("Failed to get context level: %s", e)
            return error_response(safe_error_message(e, "Get context level"), 500)

    async def _get_level_content(self, debate_id: str, level_name: str) -> dict:
        """Get content at specific abstraction level."""
        from aragora.rlm.bridge import DebateContextAdapter
        from aragora.rlm.types import AbstractionLevel

        debate_result = await self._get_debate_result(debate_id)
        if not debate_result:
            raise ValueError(f"Debate {debate_id} not found")

        adapter = DebateContextAdapter()
        context = await adapter.compress_debate(debate_result)

        try:
            level = AbstractionLevel[level_name]
        except KeyError:
            raise ValueError(f"Invalid level: {level_name}")

        content = context.get_at_level(level)
        tokens = context.total_tokens_at_level(level)

        nodes = []
        if level in context.levels:
            for node in context.levels[level]:
                nodes.append(
                    {
                        "id": node.id,
                        "content": (
                            node.content[:500] + "..." if len(node.content) > 500 else node.content
                        ),
                        "token_count": node.token_count,
                        "key_topics": node.key_topics,
                    }
                )

        return {
            "level": level_name,
            "content": content,
            "token_count": tokens,
            "nodes": nodes,
        }

    @rate_limit(requests_per_minute=120, limiter_name="rlm_status")
    @require_user_auth
    @handle_errors("refinement status")
    def _get_refinement_status(self, path: str, handler, user=None) -> HandlerResult:
        """
        Get status of an ongoing refinement process.

        Rate limited to 120 requests per minute.

        Response:
        {
            "debate_id": "...",
            "active_queries": 0,
            "cached_contexts": 1,
            "last_query_time": "..."
        }
        """
        # RBAC check
        rbac_error = self._check_permission(user, "debates.read")
        if rbac_error:
            return rbac_error

        debate_id = self._extract_debate_id(path)
        if not debate_id:
            return error_response("Invalid debate ID", 400)

        # Validate debate_id format
        if len(debate_id) > 100 or not debate_id.replace("-", "").replace("_", "").isalnum():
            return error_response("Invalid debate ID format", 400)

        # Note: In production, track active queries in a store
        return json_response(
            {
                "debate_id": debate_id,
                "active_queries": 0,
                "cached_contexts": 0,
                "status": "idle",
            }
        )

    @rate_limit(requests_per_minute=30, limiter_name="rlm_knowledge")
    @require_user_auth
    @handle_errors("RLM knowledge query")
    def _query_knowledge_rlm(self, handler, user=None) -> HandlerResult:
        """
        Query knowledge mound using RLM.

        Rate limited to 30 requests per minute.

        Request body:
        {
            "workspace_id": "ws_123",
            "query": "What are the key security requirements?",
            "max_nodes": 100,
            "strategy": "auto"
        }

        Response:
        {
            "answer": "...",
            "sources": [...],
            "confidence": 0.85
        }
        """
        # RBAC check
        rbac_error = self._check_permission(user, "knowledge.read")
        if rbac_error:
            return rbac_error

        body = handler.get_json_body()
        if not body:
            return error_response("Request body required", 400)

        workspace_id = body.get("workspace_id")
        query = body.get("query")

        if not workspace_id:
            return error_response("workspace_id is required", 400)
        if not query:
            return error_response("query is required", 400)

        # Validate workspace_id format
        if len(workspace_id) > 100 or not workspace_id.replace("-", "").replace("_", "").isalnum():
            return error_response("Invalid workspace_id format", 400)

        # Validate query length
        if len(query) > 10000:
            return error_response("Query too long (max 10000 characters)", 400)

        max_nodes = body.get("max_nodes", 100)
        if not isinstance(max_nodes, int) or max_nodes < 1 or max_nodes > 1000:
            max_nodes = 100

        strategy = body.get("strategy", "auto")
        valid_strategies = ["auto", "peek", "grep", "partition_map", "summarize", "hierarchical"]
        if strategy not in valid_strategies:
            return error_response(
                f"Invalid strategy. Must be one of: {', '.join(valid_strategies)}", 400
            )

        # Check circuit breaker
        circuit_breaker = _get_rlm_circuit_breaker("knowledge")
        if not circuit_breaker.can_proceed():
            logger.warning("RLM knowledge query circuit breaker is open")
            return error_response(
                "RLM service temporarily unavailable. Please try again later.",
                503,
            )

        try:
            result = _run_async(
                self._execute_knowledge_query(
                    workspace_id=workspace_id,
                    query=query,
                    max_nodes=max_nodes,
                    strategy=strategy,
                )
            )
            circuit_breaker.record_success()
            return json_response(result)
        except (RuntimeError, ValueError, OSError, TimeoutError, AttributeError) as e:
            circuit_breaker.record_failure()
            logger.error("Knowledge RLM query failed: %s", e)
            return error_response(safe_error_message(e, "Query"), 500)

    async def _execute_knowledge_query(
        self,
        workspace_id: str,
        query: str,
        max_nodes: int,
        strategy: str,
    ) -> dict:
        """Execute RLM query against knowledge mound."""
        from aragora.rlm.bridge import AragoraRLM, KnowledgeMoundAdapter

        try:
            from aragora.knowledge.mound import get_knowledge_mound

            mound = get_knowledge_mound(workspace_id=workspace_id)
        except ImportError:
            return {
                "answer": "Knowledge Mound not available",
                "sources": [],
                "confidence": 0.0,
            }

        rlm = AragoraRLM()
        adapter = KnowledgeMoundAdapter(mound)

        context = await adapter.to_rlm_context(
            workspace_id=workspace_id,
            query=query,
            max_nodes=max_nodes,
        )

        result = await rlm.query_with_refinement(
            query=query,
            context=context,
            strategy=strategy,
        )

        return {
            "answer": result.answer,
            "sources": result.nodes_examined,
            "confidence": result.confidence,
            "ready": result.ready,
            "iteration": result.iteration,
        }

    @rate_limit(requests_per_minute=120, limiter_name="rlm_status_endpoint")
    def _get_rlm_status(self) -> HandlerResult:
        """
        Get RLM system status.

        Rate limited to 120 requests per minute.

        Response:
        {
            "available": true,
            "provider": "built-in",
            "version": "1.0.0",
            "features": ["compression", "queries", "refinement", "streaming"],
            "circuit_breakers": {...}
        }
        """
        try:
            # Check if official RLM is available.
            # import_rlm_guarded: importing rlm triggers a load_dotenv() side
            # effect that can inject a repository .env process-wide (#8277);
            # the helper serializes the one real import so concurrent request
            # threads cannot interleave environ snapshots/restores.
            try:
                from aragora.utils.env import import_rlm_guarded

                rlm = import_rlm_guarded()
                provider = "rlm-library"
                version = getattr(rlm, "__version__", "unknown")
            except ImportError:
                provider = "built-in"
                version = "1.0.0"

            features = ["compression", "queries", "refinement"]

            # Check streaming support
            try:
                from aragora.rlm.streaming import StreamingRLMQuery  # noqa: F401

                features.append("streaming")
            except ImportError:
                pass

            # Check training support
            try:
                from aragora.rlm.training import Trainer  # noqa: F401

                features.append("training")
            except ImportError:
                pass

            # Include circuit breaker status
            circuit_breaker_status = get_rlm_circuit_breaker_status()

            return json_response(
                {
                    "available": True,
                    "provider": provider,
                    "version": version,
                    "features": features,
                    "circuit_breakers": circuit_breaker_status,
                }
            )

        except (RuntimeError, ValueError, OSError, TypeError, AttributeError) as e:
            logger.error("Failed to get RLM status: %s", e)
            return json_response(
                {
                    "available": False,
                    "provider": "unknown",
                    "version": "unknown",
                    "features": [],
                    "error": "RLM status unavailable",
                }
            )

    @rate_limit(requests_per_minute=60, limiter_name="rlm_metrics")
    def _get_rlm_metrics(self) -> HandlerResult:
        """
        Get RLM metrics for monitoring dashboard.

        Rate limited to 60 requests per minute.

        Response:
        {
            "compressions": {...},
            "queries": {...},
            "cache": {...},
            "refinement": {...}
        }
        """
        try:
            # Try to get metrics from Prometheus registry
            from aragora.rlm.metrics import (
                RLM_COMPRESSIONS,
                RLM_TOKENS_SAVED,
                RLM_QUERIES,
                RLM_CACHE_HITS,
                RLM_CACHE_MISSES,
                RLM_MEMORY_USAGE,
                RLM_REFINEMENT_SUCCESS,
                RLM_READY_FALSE_RATE,
            )

            # Extract values from Prometheus metrics
            compressions_total = self._get_counter_value(RLM_COMPRESSIONS)
            tokens_saved = self._get_counter_value(RLM_TOKENS_SAVED)
            queries_total = self._get_counter_value(RLM_QUERIES)
            cache_hits = self._get_counter_value(RLM_CACHE_HITS)
            cache_misses = self._get_counter_value(RLM_CACHE_MISSES)
            refinement_success = self._get_counter_value(RLM_REFINEMENT_SUCCESS)
            ready_false = self._get_counter_value(RLM_READY_FALSE_RATE)
            memory_bytes = self._get_gauge_value(RLM_MEMORY_USAGE)

            # Calculate derived metrics
            cache_total = cache_hits + cache_misses
            hit_rate = cache_hits / cache_total if cache_total > 0 else 0.0

            return json_response(
                {
                    "compressions": {
                        "total": int(compressions_total),
                        "byType": self._get_counter_by_label(RLM_COMPRESSIONS, "source_type"),
                        "avgRatio": 0.34,  # Would need histogram to calculate
                        "tokensSaved": int(tokens_saved),
                    },
                    "queries": {
                        "total": int(queries_total),
                        "byType": self._get_counter_by_label(RLM_QUERIES, "query_type"),
                        "avgDuration": 1.24,  # Would need histogram to calculate
                        "successRate": 0.94,  # Would need tracking
                    },
                    "cache": {
                        "hits": int(cache_hits),
                        "misses": int(cache_misses),
                        "hitRate": hit_rate,
                        "memoryBytes": int(memory_bytes),
                        "maxMemory": 268435456,  # 256MB default
                    },
                    "refinement": {
                        "avgIterations": 2.3,  # Would need histogram to calculate
                        "successRate": (
                            refinement_success / (refinement_success + ready_false)
                            if (refinement_success + ready_false) > 0
                            else 0.0
                        ),
                        "readyFalseTotal": int(ready_false),
                    },
                }
            )

        except ImportError:
            # RLM metrics module not available, return placeholder data
            logger.debug("RLM metrics module not available, returning placeholder data")
            return json_response(
                {
                    "compressions": {
                        "total": 0,
                        "byType": {},
                        "avgRatio": 0.0,
                        "tokensSaved": 0,
                    },
                    "queries": {
                        "total": 0,
                        "byType": {},
                        "avgDuration": 0.0,
                        "successRate": 0.0,
                    },
                    "cache": {
                        "hits": 0,
                        "misses": 0,
                        "hitRate": 0.0,
                        "memoryBytes": 0,
                        "maxMemory": 268435456,
                    },
                    "refinement": {
                        "avgIterations": 0.0,
                        "successRate": 0.0,
                        "readyFalseTotal": 0,
                    },
                }
            )

        except (RuntimeError, ValueError, OSError, TypeError, AttributeError) as e:
            logger.error("Failed to get RLM metrics: %s", e)
            return error_response(safe_error_message(e, "Failed to get metrics"), 500)

    def _get_counter_value(self, counter) -> float:
        """Extract total value from a Prometheus Counter."""
        try:
            return counter._value.get() if hasattr(counter, "_value") else 0.0
        except (AttributeError, TypeError):
            return 0.0

    def _get_gauge_value(self, gauge) -> float:
        """Extract value from a Prometheus Gauge."""
        try:
            return gauge._value.get() if hasattr(gauge, "_value") else 0.0
        except (AttributeError, TypeError):
            return 0.0

    def _get_counter_by_label(self, counter, label_name: str) -> dict:
        """Extract counter values grouped by a label."""
        try:
            result = {}
            if hasattr(counter, "_metrics"):
                for labels, value in counter._metrics.items():
                    if label_name in labels:
                        result[labels[label_name]] = value._value.get()
            return result
        except (AttributeError, TypeError, KeyError):
            return {}


# Export handler
__all__ = ["RLMHandler"]
