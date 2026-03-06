"""
RLM (Recursive Language Models) handler.

Provides API endpoints for RLM compression and query operations:
- Compression statistics and cache management
- Content compression with hierarchical abstraction
- Query operations on compressed contexts
- Context storage and retrieval
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
    require_auth,
    safe_error_message,
)
from aragora.server.http_utils import safe_int
from aragora.server.validation.query_params import safe_query_int
from aragora.utils.async_utils import run_async
from .utils.decorators import require_permission
from .utils.rate_limit import rate_limit

logger = logging.getLogger(__name__)


class RLMContextHandler(BaseHandler):
    """Handler for RLM context compression and query endpoints.

    This handler provides generic RLM context management APIs:
    - /api/rlm/stats - Cache and system statistics
    - /api/rlm/strategies - List decomposition strategies
    - /api/rlm/compress - Compress arbitrary content
    - /api/rlm/query - Query compressed contexts
    - /api/rlm/contexts - List stored contexts
    - /api/rlm/context/{id} - Get/delete specific context

    For debate-specific RLM operations (e.g., /api/debates/{id}/query-rlm),
    use the RLMHandler from aragora.server.handlers.features.rlm instead.
    """

    ROUTES = {
        "/api/v1/rlm/stats": "handle_stats",
        "/api/v1/rlm/strategies": "handle_strategies",
        "/api/v1/rlm/compress": "handle_compress",
        "/api/v1/rlm/query": "handle_query",
        "/api/v1/rlm/contexts": "handle_list_contexts",
        "/api/v1/rlm/stream": "handle_stream",
        "/api/v1/rlm/stream/modes": "handle_stream_modes",
        "/api/v1/rlm/codebase/health": "handle_codebase_health",
    }

    # Dynamic routes for context operations
    CONTEXT_ROUTE_PREFIX = "/api/v1/rlm/context/"

    def __init__(self, ctx: dict[str, Any]):
        """Initialize with server context."""
        super().__init__(ctx)
        # In-memory context storage (could be backed by a store in production)
        self._contexts: dict[str, dict[str, Any]] = {}
        self._compressor: Any | None = None
        self._rlm: Any | None = None

    def _get_compressor(self) -> Any:
        """Get or create the hierarchical compressor using factory."""
        if self._compressor is None:
            try:
                from aragora.rlm import get_compressor

                self._compressor = get_compressor()
            except ImportError:
                return None
        return self._compressor

    def _get_rlm(self) -> Any:
        """Get AragoraRLM instance using factory.

        Returns:
            AragoraRLM instance (routes to TRUE RLM when available).
            The factory handles TRUE RLM vs compression fallback automatically.
        """
        if self._rlm is None:
            try:
                from aragora.rlm import get_rlm, HAS_OFFICIAL_RLM

                self._rlm = get_rlm()
                if HAS_OFFICIAL_RLM:
                    logger.info("Official TRUE RLM initialized for handler")
                else:
                    logger.info("RLM initialized with compression fallback")
            except ImportError:
                return None
        return self._rlm

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the given path."""
        if path in self.ROUTES:
            return True
        if path.startswith(self.CONTEXT_ROUTE_PREFIX):
            return True
        return False

    @rate_limit(requests_per_minute=60)
    @require_permission("rlm:read")
    def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Route GET requests to appropriate methods."""
        # Check static routes first (GET-only routes)
        if path == "/api/v1/rlm/stats":
            return self.handle_stats(path, query_params, handler)
        elif path == "/api/v1/rlm/strategies":
            return self.handle_strategies(path, query_params, handler)
        elif path == "/api/v1/rlm/contexts":
            return self.handle_list_contexts(path, query_params, handler)
        elif path == "/api/v1/rlm/stream/modes":
            return self.handle_stream_modes(path, query_params, handler)
        elif path == "/api/v1/rlm/codebase/health":
            return self.handle_codebase_health(path, query_params, handler)

        # Handle context-specific routes (GET)
        if path.startswith(self.CONTEXT_ROUTE_PREFIX):
            return self._handle_context_route(path, query_params, handler)

        return None

    @handle_errors("r l m context creation")
    @rate_limit(requests_per_minute=30)
    @require_permission("rlm:create")
    def handle_post(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Route POST requests to appropriate methods."""
        if path == "/api/v1/rlm/compress":
            return self.handle_compress(path, query_params, handler)
        elif path == "/api/v1/rlm/query":
            return self.handle_query(path, query_params, handler)
        elif path == "/api/v1/rlm/stream":
            return self.handle_stream(path, query_params, handler)

        return None

    @handle_errors("r l m context deletion")
    @rate_limit(requests_per_minute=30)
    @require_permission("rlm:delete")
    def handle_delete(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Route DELETE requests to appropriate methods."""
        if path.startswith(self.CONTEXT_ROUTE_PREFIX):
            context_id = path[len(self.CONTEXT_ROUTE_PREFIX) :]
            if context_id and "/" not in context_id:
                return self._delete_context(context_id, query_params, handler)

        return None

    def _handle_context_route(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Route context-specific requests."""
        # Extract context_id from path: /api/rlm/context/{context_id}
        context_id = path[len(self.CONTEXT_ROUTE_PREFIX) :]

        # Validate context_id
        if not context_id or "/" in context_id:
            return error_response("Invalid context ID", 400)

        from aragora.server.validation import validate_path_segment, SAFE_ID_PATTERN

        is_valid, err = validate_path_segment(context_id, "context_id", SAFE_ID_PATTERN)
        if not is_valid:
            return error_response(err or "Invalid context ID", 400)

        # Determine method from request
        method = getattr(handler, "command", "GET") if handler else "GET"

        if method == "GET":
            return self._get_context(context_id, query_params, handler)
        elif method == "DELETE":
            return self._delete_context(context_id, query_params, handler)

        return error_response("Method not allowed", 405)

    # ============================================================================
    # Static Route Handlers
    # ============================================================================

    @rate_limit(requests_per_minute=60, limiter_name="rlm_stats")
    @handle_errors("get RLM stats")
    @require_permission("debates:read")
    def handle_stats(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """
        Get RLM compression statistics.

        Rate limited to 60 requests per minute.

        Returns:
            Cache statistics, context counts, and system status
        """
        try:
            from aragora.rlm.compressor import get_compression_cache_stats
            from aragora.rlm import HAS_OFFICIAL_RLM

            cache_stats = get_compression_cache_stats()

            stats = {
                "cache": cache_stats,
                "contexts": {
                    "stored": len(self._contexts),
                    "ids": list(self._contexts.keys())[:20],  # First 20 IDs
                },
                "system": {
                    "has_official_rlm": HAS_OFFICIAL_RLM,
                    "compressor_available": self._get_compressor() is not None,
                    "rlm_available": self._get_rlm() is not None,
                },
                "timestamp": datetime.now().isoformat(),
            }

            return json_response(stats)

        except ImportError as e:
            logger.warning("RLM module not fully available: %s", e)
            return json_response(
                {
                    "cache": {"error": "RLM module not available"},
                    "contexts": {"stored": len(self._contexts)},
                    "system": {
                        "has_official_rlm": False,
                        "compressor_available": False,
                        "rlm_available": False,
                    },
                    "timestamp": datetime.now().isoformat(),
                }
            )

    @rate_limit(requests_per_minute=120, limiter_name="rlm_strategies")
    @require_permission("debates:read")
    def handle_strategies(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """
        List available RLM decomposition strategies.

        Rate limited to 120 requests per minute.

        Returns:
            List of strategies with descriptions and use cases
        """
        strategies = {
            "peek": {
                "name": "Peek",
                "description": "Quick sampling of content sections",
                "use_case": "Rapid exploration, initial understanding",
                "token_reduction": "95%",
            },
            "grep": {
                "name": "Grep",
                "description": "Keyword and pattern-based content filtering",
                "use_case": "Finding specific information, searching",
                "token_reduction": "80-95%",
            },
            "partition_map": {
                "name": "Partition Map",
                "description": "Divide content and process partitions in parallel",
                "use_case": "Large documents, comprehensive analysis",
                "token_reduction": "60-80%",
            },
            "summarize": {
                "name": "Summarize",
                "description": "Hierarchical summarization at multiple abstraction levels",
                "use_case": "Long documents, getting the gist",
                "token_reduction": "70-90%",
            },
            "hierarchical": {
                "name": "Hierarchical",
                "description": "Build abstraction tree with drill-down capability",
                "use_case": "Complex documents, iterative exploration",
                "token_reduction": "50-90%",
            },
            "auto": {
                "name": "Auto",
                "description": "Automatically select best strategy based on content and query",
                "use_case": "General purpose, when unsure which strategy to use",
                "token_reduction": "varies",
            },
        }

        return json_response(
            {
                "strategies": strategies,
                "default": "auto",
                "documentation": "https://github.com/alexzhang13/rlm",
            }
        )

    @rate_limit(requests_per_minute=20, limiter_name="rlm_codebase_health")
    @handle_errors("get RLM codebase health")
    @require_permission("debates:read")
    def handle_codebase_health(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Return health and readiness info for codebase RLM context."""
        from aragora.rlm import HAS_OFFICIAL_RLM
        from aragora.rlm.codebase_context import CodebaseContextBuilder

        def _parse_bool(value: Any) -> bool | None:
            if value is None:
                return None
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"1", "true", "yes", "y"}:
                    return True
                if lowered in {"0", "false", "no", "n"}:
                    return False
            return None

        root = Path(
            os.environ.get("ARAGORA_CODEBASE_ROOT")
            or os.environ.get("ARAGORA_REPO_ROOT")
            or os.getcwd()
        ).resolve()
        if not root.exists():
            return error_response(f"Codebase root not found: {root}", 404)

        refresh = _parse_bool(query_params.get("refresh")) is True
        include_tests = _parse_bool(query_params.get("include_tests"))
        full_corpus = _parse_bool(query_params.get("full_corpus"))
        build_rlm = _parse_bool(query_params.get("rlm")) is True
        max_bytes = safe_int(query_params.get("max_bytes"), 0)

        builder = CodebaseContextBuilder(
            root_path=root,
            max_context_bytes=max_bytes or 0,
            include_tests=include_tests,
            full_corpus=full_corpus,
        )

        context_dir = root / ".nomic" / "context"
        manifest_path = context_dir / "codebase_manifest.tsv"

        manifest_info: dict[str, Any] = {
            "exists": manifest_path.exists(),
            "path": str(manifest_path) if manifest_path.exists() else None,
        }
        if manifest_path.exists():
            try:
                header_lines = []
                with manifest_path.open("r", encoding="utf-8") as handle:
                    for _ in range(5):
                        line = handle.readline()
                        if not line or not line.startswith("#"):
                            break
                        header_lines.append(line.strip())
                for line in header_lines:
                    if "files=" in line and "lines=" in line:
                        parts = line.split()
                        for part in parts:
                            if part.startswith("files="):
                                manifest_info["files"] = safe_int(part.split("=", 1)[1], 0)
                            if part.startswith("lines="):
                                manifest_info["lines"] = safe_int(part.split("=", 1)[1], 0)
            except OSError as exc:
                manifest_info["error"] = str(exc)

        index_info: dict[str, Any] | None = None
        if refresh:
            index = run_async(builder.build_index())
            index_info = {
                "files": index.total_files,
                "lines": index.total_lines,
                "bytes": index.total_bytes,
                "tokens_estimate": index.total_tokens_estimate,
                "build_time_seconds": index.build_time_seconds,
            }

        rlm_context_ready = None
        if build_rlm:
            context = run_async(builder.build_rlm_context())
            rlm_context_ready = context is not None

        status = "available" if manifest_info.get("exists") or index_info else "missing"
        response = {
            "status": status,
            "root": str(root),
            "context_dir": str(context_dir),
            "manifest": manifest_info,
            "index": index_info,
            "rlm": {
                "has_official_rlm": HAS_OFFICIAL_RLM,
                "rlm_available": self._get_rlm() is not None,
                "context_ready": rlm_context_ready,
                "max_content_bytes": max_bytes or None,
            },
            "timestamp": datetime.now().isoformat(),
        }
        return json_response(response)

    @require_auth
    @rate_limit(requests_per_minute=20, limiter_name="rlm_compress")
    @handle_errors("compress content")
    @require_permission("debates:read")
    def handle_compress(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """
        Compress content and return a context ID.

        Requires authentication. Rate limited to 20 requests per minute.

        Request body (JSON):
            content: str - The content to compress
            source_type: str - Type of content (text, code, debate) (default: text)
            levels: int - Number of abstraction levels (default: 4)

        Returns:
            context_id: str - ID for retrieving the compressed context
            compression_result: dict - Statistics about the compression
        """
        # Read request body
        body = self.read_json_body(handler)
        if body is None:
            return error_response("Request body required", 400)

        content = body.get("content")
        if not content or not isinstance(content, str):
            return error_response("'content' field required and must be a string", 400)

        # Validate content size
        if len(content) > 10_000_000:  # 10MB limit
            return error_response("Content too large (max 10MB)", 413)

        source_type = body.get("source_type", "text")
        if source_type not in ("text", "code", "debate"):
            return error_response(
                "Invalid source_type. Must be 'text', 'code', or 'debate'",
                400,
            )

        levels = body.get("levels", 4)
        if not isinstance(levels, int) or levels < 1 or levels > 5:
            return error_response("'levels' must be an integer between 1 and 5", 400)

        compressor = self._get_compressor()
        if compressor is None:
            return error_response(
                "RLM compressor not available",
                503,
                details={"hint": "RLM module may not be installed"},
            )

        try:
            # Run compression asynchronously
            context = run_async(compressor.compress(content, source_type=source_type))

            # Generate context ID from content hash
            content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
            context_id = f"ctx_{content_hash}_{int(datetime.now().timestamp())}"

            # Store context
            self._contexts[context_id] = {
                "context": context,
                "created_at": datetime.now().isoformat(),
                "source_type": source_type,
                "original_tokens": context.original_tokens,
            }

            # Build compression result
            level_stats = {}
            for level, nodes in context.levels.items():
                level_stats[level.name if hasattr(level, "name") else str(level)] = {
                    "nodes": len(nodes),
                    "tokens": sum(n.token_count for n in nodes),
                }

            compression_ratio = (
                context.total_tokens() / context.original_tokens
                if context.original_tokens > 0
                else 1.0
            )

            logger.info(
                "rlm_compress context_id=%s source_type=%s original_tokens=%d ratio=%.2f",
                context_id,
                source_type,
                context.original_tokens,
                compression_ratio,
            )

            return json_response(
                {
                    "context_id": context_id,
                    "compression_result": {
                        "original_tokens": context.original_tokens,
                        "compressed_tokens": context.total_tokens(),
                        "compression_ratio": compression_ratio,
                        "levels": level_stats,
                        "source_type": source_type,
                    },
                    "created_at": datetime.now().isoformat(),
                }
            )

        except asyncio.CancelledError as e:
            logger.exception("Compression cancelled: %s", e)
            return error_response("Operation cancelled", 500)
        except (RuntimeError, asyncio.TimeoutError) as e:
            logger.exception("Compression async operation failed: %s", e)
            return error_response(safe_error_message(e, "compression"), 500)
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            logger.warning("Compression data processing error: %s", e)
            return error_response(safe_error_message(e, "compression"), 500)

    @require_auth
    @rate_limit(requests_per_minute=30, limiter_name="rlm_query")
    @handle_errors("query context")
    @require_permission("debates:read")
    def handle_query(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """
        Query a compressed context.

        Requires authentication. Rate limited to 30 requests per minute.

        Request body (JSON):
            context_id: str - ID of the compressed context
            query: str - The question to answer
            strategy: str - Decomposition strategy (default: auto)
            refine: bool - Whether to use iterative refinement (default: false)
            max_iterations: int - Max refinement iterations (default: 3)

        Returns:
            answer: str - The answer to the query
            metadata: dict - Query execution metadata
        """
        # Read request body
        body = self.read_json_body(handler)
        if body is None:
            return error_response("Request body required", 400)

        context_id = body.get("context_id")
        query = body.get("query")

        if not context_id:
            return error_response("'context_id' field required", 400)
        if not query or not isinstance(query, str):
            return error_response("'query' field required and must be a string", 400)

        # Validate query length
        if len(query) > 10000:
            return error_response("Query too long (max 10000 characters)", 400)

        # Get stored context
        if context_id not in self._contexts:
            return error_response(f"Context not found: {context_id}", 404)

        context_data = self._contexts[context_id]
        context = context_data["context"]

        strategy = body.get("strategy", "auto")
        valid_strategies = ["peek", "grep", "partition_map", "summarize", "hierarchical", "auto"]
        if strategy not in valid_strategies:
            return error_response(
                f"Invalid strategy. Must be one of: {', '.join(valid_strategies)}",
                400,
            )

        refine = body.get("refine", False)
        max_iterations = body.get("max_iterations", 3)
        if not isinstance(max_iterations, int) or max_iterations < 1 or max_iterations > 10:
            max_iterations = 3

        rlm = self._get_rlm()
        if rlm is None:
            # Fallback: simple context search if full RLM not available
            return self._fallback_query(context, query, strategy)

        try:
            # Run query asynchronously
            if refine:
                result = run_async(
                    rlm.query_with_refinement(
                        query,
                        context,
                        strategy,
                        max_iterations=max_iterations,
                    )
                )
            else:
                result = run_async(rlm.query(query, context, strategy))

            logger.info(
                "rlm_query context_id=%s strategy=%s refine=%s confidence=%.2f",
                context_id,
                strategy,
                refine,
                getattr(result, "confidence", 0.0),
            )

            return json_response(
                {
                    "answer": result.answer,
                    "metadata": {
                        "context_id": context_id,
                        "strategy": strategy,
                        "refined": refine,
                        "confidence": getattr(result, "confidence", None),
                        "iterations": getattr(result, "iteration", 1),
                        "tokens_processed": getattr(result, "tokens_processed", None),
                        "sub_calls_made": getattr(result, "sub_calls_made", None),
                    },
                    "timestamp": datetime.now().isoformat(),
                }
            )

        except asyncio.CancelledError as e:
            logger.exception("Query cancelled: %s", e)
            return error_response("Operation cancelled", 500)
        except (RuntimeError, asyncio.TimeoutError) as e:
            logger.exception("Query async operation failed: %s", e)
            return error_response(safe_error_message(e, "query"), 500)
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            logger.warning("Query data processing error: %s", e)
            return error_response(safe_error_message(e, "query"), 500)

    def _fallback_query(
        self,
        context: Any,
        query: str,
        strategy: str,
    ) -> HandlerResult:
        """Simple fallback query when full RLM is not available."""
        # Get summary level content
        try:
            from aragora.rlm import AbstractionLevel

            summary_content = context.get_at_level(AbstractionLevel.SUMMARY)
            if summary_content:
                combined = "\n".join(node.content for node in summary_content[:5])  # First 5 nodes
                return json_response(
                    {
                        "answer": f"[Fallback mode - RLM not fully available]\n\nBased on the summary:\n{combined[:2000]}",
                        "metadata": {
                            "strategy": strategy,
                            "fallback": True,
                            "nodes_examined": min(5, len(summary_content)),
                        },
                        "timestamp": datetime.now().isoformat(),
                    }
                )
        except (ImportError, AttributeError, KeyError, TypeError) as e:
            logger.warning("Fallback query could not retrieve summary content: %s", e)

        return json_response(
            {
                "answer": "[Fallback mode - Unable to process query]",
                "metadata": {"fallback": True, "error": "No summary content available"},
                "timestamp": datetime.now().isoformat(),
            }
        )

    @rate_limit(requests_per_minute=60, limiter_name="rlm_contexts")
    @require_permission("debates:read")
    def handle_list_contexts(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """
        List stored compressed contexts.

        Rate limited to 60 requests per minute.

        Query params:
            limit: int - Maximum results (default: 50)
            offset: int - Starting offset (default: 0)

        Returns:
            List of context IDs with metadata
        """
        limit = safe_query_int(query_params, "limit", default=50, max_val=100)
        offset = safe_query_int(query_params, "offset", default=0, min_val=0, max_val=100000)

        # Get context list
        all_ids = list(self._contexts.keys())
        total = len(all_ids)
        selected_ids = all_ids[offset : offset + limit]

        contexts = []
        for ctx_id in selected_ids:
            ctx_data = self._contexts[ctx_id]
            contexts.append(
                {
                    "id": ctx_id,
                    "source_type": ctx_data.get("source_type", "unknown"),
                    "original_tokens": ctx_data.get("original_tokens", 0),
                    "created_at": ctx_data.get("created_at"),
                }
            )

        return json_response(
            {
                "contexts": contexts,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )

    # ============================================================================
    # Context-Specific Route Handlers
    # ============================================================================

    def _get_context(
        self,
        context_id: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Get details of a specific compressed context."""
        if context_id not in self._contexts:
            return error_response(f"Context not found: {context_id}", 404)

        ctx_data = self._contexts[context_id]
        context = ctx_data["context"]

        # Build level statistics
        level_stats = {}
        try:
            for level, nodes in context.levels.items():
                level_name = level.name if hasattr(level, "name") else str(level)
                level_stats[level_name] = {
                    "nodes": len(nodes),
                    "tokens": sum(n.token_count for n in nodes),
                    "node_ids": [n.id for n in nodes[:10]],  # First 10 node IDs
                }
        except (AttributeError, KeyError, TypeError) as e:
            logger.warning("Error building level stats: %s", e)

        include_content = query_params.get("include_content", "false").lower() == "true"

        response = {
            "id": context_id,
            "source_type": ctx_data.get("source_type", "unknown"),
            "original_tokens": context.original_tokens,
            "compressed_tokens": context.total_tokens(),
            "compression_ratio": (
                context.total_tokens() / context.original_tokens
                if context.original_tokens > 0
                else 1.0
            ),
            "levels": level_stats,
            "created_at": ctx_data.get("created_at"),
        }

        if include_content:
            # Include summary content for preview
            try:
                from aragora.rlm import AbstractionLevel

                summary_nodes = context.get_at_level(AbstractionLevel.SUMMARY)
                if summary_nodes:
                    response["summary_preview"] = [
                        {"id": n.id, "content": n.content[:500]} for n in summary_nodes[:5]
                    ]
            except (ImportError, AttributeError, KeyError, TypeError) as e:
                logger.warning("Could not retrieve summary preview: %s", e)

        return json_response(response)

    @require_auth
    @require_permission("rlm:delete")
    def _delete_context(
        self,
        context_id: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Delete a compressed context."""
        if context_id not in self._contexts:
            return error_response(f"Context not found: {context_id}", 404)

        del self._contexts[context_id]

        logger.info("rlm_context_deleted context_id=%s", context_id)

        return json_response(
            {
                "success": True,
                "context_id": context_id,
                "message": "Context deleted",
            }
        )

    # ============================================================================
    # Utility Methods
    # ============================================================================

    def read_json_body(self, handler: Any, max_size: int | None = None) -> dict[str, Any] | None:
        """Read and parse JSON body from request.

        Args:
            handler: The HTTP request handler with headers and rfile
            max_size: Maximum body size to accept (default: 10MB)

        Returns:
            Parsed JSON dict, or None for parse errors or missing body
        """
        if handler is None:
            return None

        # Use provided max_size or default to 10MB
        effective_max_size = max_size if max_size is not None else 10_000_000

        try:
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length == 0:
                return None

            # Limit body size
            if content_length > effective_max_size:
                return None

            raw_body = handler.rfile.read(content_length)
            return json.loads(raw_body.decode("utf-8"))
        except (json.JSONDecodeError, ValueError, AttributeError) as e:
            logger.debug("Failed to parse JSON body: %s", e)
            return None

    # ============================================================================
    # Streaming Handlers
    # ============================================================================

    @rate_limit(requests_per_minute=30, limiter_name="rlm_stream_modes")
    @handle_errors("get stream modes")
    @require_permission("debates:read")
    def handle_stream_modes(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """
        Get available streaming modes.

        Returns:
            List of streaming modes with descriptions.
        """
        try:
            from aragora.rlm.streaming import StreamMode

            modes = [
                {
                    "mode": StreamMode.TOP_DOWN.value,
                    "description": "Start with abstract summaries, drill down to details",
                    "use_case": "When you need quick overview first",
                },
                {
                    "mode": StreamMode.BOTTOM_UP.value,
                    "description": "Start with details, roll up to summaries",
                    "use_case": "When you need specific details first",
                },
                {
                    "mode": StreamMode.TARGETED.value,
                    "description": "Jump directly to a specific abstraction level",
                    "use_case": "When you know exactly what level you need",
                },
                {
                    "mode": StreamMode.PROGRESSIVE.value,
                    "description": "Load content progressively with configurable delays",
                    "use_case": "For UI streaming with real-time updates",
                },
            ]
            return json_response({"modes": modes})
        except ImportError:
            return json_response(
                {
                    "modes": [
                        {"mode": "top_down", "description": "Top-down streaming"},
                        {"mode": "bottom_up", "description": "Bottom-up streaming"},
                        {"mode": "targeted", "description": "Targeted level access"},
                        {"mode": "progressive", "description": "Progressive loading"},
                    ],
                    "note": "Full streaming module not available",
                }
            )

    @rate_limit(requests_per_minute=30, limiter_name="rlm_stream")
    @handle_errors("stream context")
    @require_permission("debates:read")
    def handle_stream(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """
        Stream context with configurable modes.

        POST body:
            context_id: str - ID of stored compressed context
            mode: str - Streaming mode (top_down, bottom_up, targeted, progressive)
            query: str - Optional search query for filtering
            level: str - Optional starting level (for targeted mode)
            chunk_size: int - Approximate tokens per chunk (default: 500)
            include_metadata: bool - Include chunk metadata (default: true)

        Returns:
            Streamed chunks with content at different abstraction levels.
        """
        body = self.read_json_body(handler)
        if body is None:
            return error_response("JSON body required", 400)

        context_id = body.get("context_id")
        if not context_id:
            return error_response("'context_id' field required", 400)

        if context_id not in self._contexts:
            return error_response(f"Context not found: {context_id}", 404)

        context_data = self._contexts[context_id]
        context = context_data["context"]

        # Parse streaming configuration
        mode_str = body.get("mode", "top_down")
        query = body.get("query")
        level = body.get("level")
        chunk_size = body.get("chunk_size", 500)
        include_metadata = body.get("include_metadata", True)

        try:
            from aragora.rlm.streaming import (
                StreamConfig,
                StreamMode,
                StreamingRLMQuery,
            )

            # Map mode string to enum
            mode_map = {
                "top_down": StreamMode.TOP_DOWN,
                "bottom_up": StreamMode.BOTTOM_UP,
                "targeted": StreamMode.TARGETED,
                "progressive": StreamMode.PROGRESSIVE,
            }
            mode = mode_map.get(mode_str, StreamMode.TOP_DOWN)

            # Create streaming config
            config = StreamConfig(
                mode=mode,
                chunk_size=int(chunk_size),
                include_metadata=bool(include_metadata),
            )

            # Create streaming query
            stream_query = StreamingRLMQuery(context, config=config)

            # Collect chunks synchronously for HTTP response
            # (WebSocket would allow true streaming)
            chunks = []

            async def collect_chunks():
                if query:
                    async for chunk in stream_query.search(query):
                        chunks.append(
                            {
                                "level": chunk.level,
                                "content": chunk.content,
                                "token_count": chunk.token_count,
                                "is_final": chunk.is_final,
                                "metadata": chunk.metadata if include_metadata else {},
                            }
                        )
                elif level:
                    async for chunk in stream_query.drill_down(level):
                        chunks.append(
                            {
                                "level": chunk.level,
                                "content": chunk.content,
                                "token_count": chunk.token_count,
                                "is_final": chunk.is_final,
                                "metadata": chunk.metadata if include_metadata else {},
                            }
                        )
                else:
                    async for chunk in stream_query.stream_all():
                        chunks.append(
                            {
                                "level": chunk.level,
                                "content": chunk.content,
                                "token_count": chunk.token_count,
                                "is_final": chunk.is_final,
                                "metadata": chunk.metadata if include_metadata else {},
                            }
                        )

            # Run async collection
            run_async(collect_chunks())

            logger.info(
                "rlm_stream context_id=%s mode=%s chunks=%d",
                context_id,
                mode_str,
                len(chunks),
            )

            return json_response(
                {
                    "context_id": context_id,
                    "mode": mode_str,
                    "query": query,
                    "chunks": chunks,
                    "total_chunks": len(chunks),
                    "timestamp": datetime.now().isoformat(),
                }
            )

        except ImportError:
            # Fallback: return summary content as single chunk
            logger.warning("Streaming module not available, using fallback")
            try:
                from aragora.rlm import AbstractionLevel

                summary_nodes = context.get_at_level(AbstractionLevel.SUMMARY)
                if summary_nodes:
                    content = "\n".join(n.content for n in summary_nodes[:10])
                    return json_response(
                        {
                            "context_id": context_id,
                            "mode": "fallback",
                            "chunks": [
                                {
                                    "level": "summary",
                                    "content": content,
                                    "token_count": len(content.split()),
                                    "is_final": True,
                                }
                            ],
                            "total_chunks": 1,
                            "note": "Streaming module not available",
                            "timestamp": datetime.now().isoformat(),
                        }
                    )
            except (ImportError, AttributeError, TypeError):
                pass

            return error_response(
                "RLM streaming module not available. "
                "Install streaming dependencies with: pip install aragora[streaming]",
                501,
            )
