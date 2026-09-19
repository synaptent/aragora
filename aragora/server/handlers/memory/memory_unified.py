"""
Unified Memory Gateway HTTP Handler (DEPRECATED).

.. deprecated::
    Use ``UnifiedMemoryHandler`` in ``aragora.server.handlers.memory.unified_handler``
    (serves ``/api/v1/memory/unified/*``) instead.  This handler serves the legacy
    unversioned ``/api/memory/unified/*`` routes and will be removed in a future
    release once all consumers have migrated.

Provides REST API endpoints for the Unified Memory Gateway:
- Fan-out search across ContinuumMemory, KM, Supermemory, claude-mem
- RetentionGate decision feed (retain/demote/forget/consolidate)
- Cross-system near-duplicate detection clusters
- Memory source breakdown and status

Endpoints:
    POST /api/memory/unified/query         - Fan-out search across all systems
    GET  /api/memory/unified/retention      - RetentionGate decisions
    GET  /api/memory/unified/dedup          - Near-duplicate clusters
    GET  /api/memory/unified/sources        - Memory source breakdown
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
)
from aragora.server.handlers.utils.decorators import handle_errors
from aragora.server.handlers.utils.rate_limit import rate_limit

try:
    from aragora.rbac.decorators import require_permission
except ImportError:  # pragma: no cover

    def require_permission(*_a, **_kw):  # type: ignore[misc]
        def _noop(fn):  # type: ignore[no-untyped-def]
            return fn

        return _noop


logger = logging.getLogger(__name__)


class MemoryUnifiedHandler(BaseHandler):
    """HTTP handler for Unified Memory Gateway endpoints."""

    ROUTES = [
        "/api/memory/unified/query",
        "/api/memory/unified/retention",
        "/api/memory/unified/dedup",
        "/api/memory/unified/sources",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the request."""
        if path == "/api/memory/unified/query":
            return method == "POST"
        return method == "GET" and path in (
            "/api/memory/unified/retention",
            "/api/memory/unified/dedup",
            "/api/memory/unified/sources",
        )

    @require_permission("memory:read")
    def handle_get(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Dispatch GET requests."""
        if path == "/api/memory/unified/retention":
            return self._handle_retention(query_params)
        if path == "/api/memory/unified/dedup":
            return self._handle_dedup(query_params)
        if path == "/api/memory/unified/sources":
            return self._handle_sources()
        return None

    @require_permission("memory:write")
    @handle_errors("unified memory query")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Dispatch POST requests."""
        if path == "/api/memory/unified/query":
            body = self._get_request_body(handler)
            return self._handle_query(body)
        return None

    @rate_limit(requests_per_minute=30)
    def _handle_query(self, body: dict[str, Any]) -> HandlerResult:
        """POST /api/memory/unified/query — Fan-out search."""
        query = body.get("query", "").strip()
        if not query:
            return error_response("Missing required field: query", 400)

        requested_systems = body.get("systems", ["continuum", "km", "supermemory", "claude_mem"])
        limit = min(body.get("limit", 20), 100)

        results: list[dict[str, Any]] = []
        per_system: dict[str, int] = {}

        # Query each system with graceful fallback
        for system in requested_systems:
            system_results = self._query_system(system, query, limit)
            per_system[system] = len(system_results)
            results.extend(system_results)

        # Sort by relevance and limit
        results.sort(key=lambda r: r.get("relevance", 0), reverse=True)
        results = results[:limit]

        return json_response(
            {
                "data": {
                    "results": results,
                    "total": len(results),
                    "per_system": per_system,
                    "query": query,
                }
            }
        )

    def _query_system(self, system: str, query: str, limit: int) -> list[dict[str, Any]]:
        """Query a single memory system."""
        try:
            if system == "continuum":
                return self._query_continuum(query, limit)
            elif system == "km":
                return self._query_km(query, limit)
            elif system == "supermemory":
                return self._query_supermemory(query, limit)
            elif system == "claude_mem":
                return self._query_claude_mem(query, limit)
        except (
            ImportError,
            RuntimeError,
            ValueError,
            TypeError,
            OSError,
            AttributeError,
            KeyError,
        ) as e:
            logger.warning("Memory system %s query failed: %s", system, e)
        return []

    def _query_continuum(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Query ContinuumMemory."""
        try:
            from aragora.memory.continuum import ContinuumMemory

            memory = ContinuumMemory()
            entries = memory.retrieve(query=query, limit=limit)
            return [
                {
                    "content": getattr(e, "content", str(e)),
                    "source": "continuum",
                    "relevance": getattr(e, "relevance", 0.5),
                    "metadata": {
                        "tier": getattr(e, "tier", "unknown"),
                        "created_at": str(getattr(e, "created_at", "")),
                    },
                }
                for e in (entries or [])
            ]
        except (ImportError, AttributeError):
            return []

    def _query_km(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Query Knowledge Mound."""
        try:
            from aragora.knowledge.mound import KnowledgeMound

            km: Any = KnowledgeMound()  # type: ignore[abstract]
            entries = km.query(query, limit=limit)
            return [
                {
                    "content": getattr(e, "content", str(e)),
                    "source": "km",
                    "relevance": getattr(e, "confidence", 0.5),
                    "metadata": {
                        "node_type": getattr(e, "node_type", "fact"),
                        "adapter": getattr(e, "source_adapter", ""),
                    },
                }
                for e in (entries or [])
            ]
        except (ImportError, AttributeError):
            return []

    def _query_supermemory(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Query Supermemory."""
        try:
            from aragora.memory.backends.supermemory import SupermemoryBackend

            store = SupermemoryBackend()
            entries = store.search(query, limit=limit)
            return [
                {
                    "content": getattr(e, "content", str(e)),
                    "source": "supermemory",
                    "relevance": getattr(e, "relevance", 0.5),
                    "metadata": {
                        "session_id": getattr(e, "session_id", ""),
                    },
                }
                for e in (entries or [])
            ]
        except (ImportError, AttributeError):
            return []

    def _query_claude_mem(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Query claude-mem MCP adapter."""
        try:
            from aragora.knowledge.mound.adapters.claude_mem_adapter import ClaudeMemAdapter

            adapter = ClaudeMemAdapter()
            entries = adapter.search(query, limit=limit)
            return [
                {
                    "content": getattr(e, "content", str(e)),
                    "source": "claude_mem",
                    "relevance": getattr(e, "relevance", 0.5),
                    "metadata": {},
                }
                for e in (entries or [])
            ]
        except (ImportError, AttributeError):
            return []

    def _handle_retention(self, query_params: dict[str, Any]) -> HandlerResult:
        """GET /api/memory/unified/retention — RetentionGate decisions."""
        limit = min(int(query_params.get("limit", "50")), 200)

        try:
            from aragora.memory.retention_gate import RetentionGate

            gate = RetentionGate()
            history = (
                gate.get_decision_history(limit=limit)
                if hasattr(gate, "get_decision_history")
                else []
            )

            decisions = []
            stats = {"retained": 0, "demoted": 0, "forgotten": 0, "consolidated": 0}

            action_to_stats_key = {
                "retain": "retained",
                "retained": "retained",
                "demote": "demoted",
                "demoted": "demoted",
                "forget": "forgotten",
                "forgotten": "forgotten",
                "consolidate": "consolidated",
                "consolidated": "consolidated",
            }

            for d in history or []:
                action = str(getattr(d, "action", "retain")).strip().lower()
                stats_key = action_to_stats_key.get(action, action)
                stats[stats_key] = stats.get(stats_key, 0) + 1
                decisions.append(
                    {
                        "memory_id": getattr(d, "memory_id", ""),
                        "action": action,
                        "surprise_score": getattr(d, "surprise_score", 0.0),
                        "reason": getattr(d, "reason", ""),
                        "timestamp": str(getattr(d, "timestamp", "")),
                    }
                )

            return json_response({"data": {"decisions": decisions, "stats": stats}})
        except (ImportError, AttributeError) as e:
            logger.warning("RetentionGate unavailable: %s", e)
            return json_response(
                {
                    "data": {
                        "decisions": [],
                        "stats": {"retained": 0, "demoted": 0, "forgotten": 0, "consolidated": 0},
                        "message": "RetentionGate not configured",
                    }
                }
            )

    def _handle_dedup(self, query_params: dict[str, Any]) -> HandlerResult:
        """GET /api/memory/unified/dedup — Near-duplicate clusters."""
        try:
            from aragora.memory.dedup import CrossSystemDedupEngine

            engine = CrossSystemDedupEngine()
            clusters = engine.get_clusters() if hasattr(engine, "get_clusters") else []

            cluster_data = []
            for c in clusters or []:
                cluster_data.append(
                    {
                        "cluster_id": getattr(c, "cluster_id", ""),
                        "entries": [
                            {
                                "content": getattr(e, "content", str(e)),
                                "source": getattr(e, "source", ""),
                                "similarity": getattr(e, "similarity", 0.0),
                            }
                            for e in getattr(c, "entries", [])
                        ],
                        "canonical": getattr(c, "canonical_id", ""),
                    }
                )

            return json_response(
                {
                    "data": {
                        "clusters": cluster_data,
                        "total_duplicates": sum(len(c.get("entries", [])) for c in cluster_data),
                    }
                }
            )
        except (ImportError, AttributeError) as e:
            logger.warning("DedupEngine unavailable: %s", e)
            return json_response(
                {
                    "data": {
                        "clusters": [],
                        "total_duplicates": 0,
                        "message": "DedupEngine not configured",
                    }
                }
            )

    def _handle_sources(self) -> HandlerResult:
        """GET /api/memory/unified/sources — Memory source breakdown."""
        sources = []

        # Check each memory system availability
        system_checks = [
            ("continuum", "aragora.memory.continuum", "ContinuumMemory"),
            ("km", "aragora.knowledge.mound", "KnowledgeMound"),
            ("supermemory", "aragora.memory.backends.supermemory", "SupermemoryBackend"),
            (
                "claude_mem",
                "aragora.knowledge.mound.adapters.claude_mem_adapter",
                "ClaudeMemAdapter",
            ),
        ]

        for name, module_path, class_name in system_checks:
            try:
                import importlib

                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name)
                instance = cls()
                count = getattr(instance, "count", lambda: 0)()
                sources.append(
                    {
                        "name": name,
                        "entry_count": count if isinstance(count, int) else 0,
                        "status": "active",
                        "last_activity": datetime.now(timezone.utc).isoformat(),
                    }
                )
            except (ImportError, AttributeError, TypeError):
                sources.append(
                    {
                        "name": name,
                        "entry_count": 0,
                        "status": "unavailable",
                        "last_activity": None,
                    }
                )

        return json_response({"data": {"sources": sources}})

    @staticmethod
    def _get_request_body(handler: Any) -> dict[str, Any]:
        """Extract JSON body from the request handler."""
        import json

        try:
            if hasattr(handler, "request") and hasattr(handler.request, "body"):
                raw = handler.request.body
                if raw:
                    return json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            pass
        return {}
