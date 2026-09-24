"""
Knowledge Flow HTTP Handler — Debate -> KM -> Debate flywheel visualization.

Provides REST API endpoints for the Knowledge Flywheel:
- Aggregated debate->KM->debate flow data
- Confidence score history over time
- KM adapter health statuses

Endpoints:
    GET  /api/knowledge/flow                     - Flow data (debate->KM->debate)
    GET  /api/knowledge/flow/confidence-history   - Confidence changes over time
    GET  /api/knowledge/adapters/health           - All adapter statuses
"""

from __future__ import annotations

import importlib
import logging
from datetime import datetime, timezone
from typing import Any

from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
)

try:
    from aragora.rbac.decorators import require_permission
except ImportError:  # pragma: no cover

    def require_permission(*_a, **_kw):  # type: ignore[misc]
        def _noop(fn):  # type: ignore[no-untyped-def]
            return fn

        return _noop


logger = logging.getLogger(__name__)


class KnowledgeFlowHandler(BaseHandler):
    """HTTP handler for Knowledge Flywheel visualization endpoints."""

    ROUTES = [
        "/api/knowledge/flow",
        "/api/knowledge/flow/*",
        "/api/knowledge/adapters/health",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the request."""
        if method != "GET":
            return False
        return (
            path == "/api/knowledge/flow"
            or path == "/api/knowledge/flow/confidence-history"
            or path == "/api/knowledge/adapters/health"
        )

    @require_permission("knowledge:read")
    async def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Route request to appropriate handler method."""
        query_params = query_params or {}

        try:
            if path == "/api/knowledge/flow":
                return await self._get_flow_data(query_params)

            if path == "/api/knowledge/flow/confidence-history":
                return await self._get_confidence_history(query_params)

            if path == "/api/knowledge/adapters/health":
                return await self._get_adapter_health()

            return error_response("Not found", 404)

        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            logger.exception("Error handling knowledge flow request: %s", e)
            return error_response("Internal server error", 500)

    async def _get_flow_data(self, query_params: dict[str, Any]) -> HandlerResult:
        """Get aggregated debate->KM->debate flow data.

        Returns flow connections showing how knowledge from one debate
        enriches subsequent debates through the Knowledge Mound.
        """
        bridge = self._get_km_outcome_bridge()

        flows: list[dict[str, Any]] = []
        stats = {
            "total_flows": 0,
            "avg_confidence_change": 0.0,
            "debates_enriched": 0,
        }

        if bridge is not None:
            bridge_stats = bridge.get_validation_stats()
            validations = getattr(bridge, "_validations_applied", [])
            debate_usage = getattr(bridge, "_debate_km_usage", {})

            for validation in validations:
                flows.append(
                    {
                        "source_debate_id": validation.debate_id,
                        "km_node_id": validation.km_item_id,
                        "target_debate_id": None,
                        "confidence_delta": round(validation.confidence_adjustment, 4),
                        "original_confidence": round(validation.original_confidence, 4),
                        "new_confidence": round(validation.new_confidence, 4),
                        "was_successful": validation.was_successful,
                        "reason": validation.validation_reason,
                        "content_preview": f"KM node {validation.km_item_id}",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )

            stats["total_flows"] = bridge_stats.get("total_validations", 0)
            stats["debates_enriched"] = bridge_stats.get("debates_tracked", 0)

            total_adj = sum(abs(v.confidence_adjustment) for v in validations)
            if validations:
                stats["avg_confidence_change"] = round(total_adj / len(validations), 4)

            # Cross-reference: if a KM item used in debate A was also
            # consumed in debate B, that's a complete flow
            km_to_source: dict[str, str] = {}
            for v in validations:
                km_to_source[v.km_item_id] = v.debate_id

            for debate_id, km_ids in debate_usage.items():
                for km_id in km_ids:
                    source = km_to_source.get(km_id)
                    if source and source != debate_id:
                        # Update matching flow entry
                        for flow in flows:
                            if flow["km_node_id"] == km_id and flow["source_debate_id"] == source:
                                flow["target_debate_id"] = debate_id
                                break

        # Include cross-adapter synthesis data from FeedbackPhase step 38
        synthesis_data: dict[str, Any] = {"count": 0, "recent": []}
        try:
            from aragora.knowledge.mound.adapters.factory import get_adapter

            mound = self._get_knowledge_mound()
            if mound:
                insight_adapter = get_adapter("insights", mound)
                if insight_adapter and hasattr(insight_adapter, "search_by_topic"):
                    results = insight_adapter.search_by_topic("cross-adapter-synthesis", limit=5)
                    for r in results or []:
                        meta = r if isinstance(r, dict) else getattr(r, "__dict__", {})
                        item_meta = meta.get("metadata", {})
                        if item_meta.get("type") == "synthesis":
                            synthesis_data["count"] += 1
                            synthesis_data["recent"].append(
                                {
                                    "debate_id": item_meta.get("debate_id", ""),
                                    "topic": item_meta.get("topic", "")[:100],
                                    "confidence": meta.get("confidence", 0),
                                }
                            )
        except (ImportError, AttributeError, TypeError, RuntimeError):
            pass

        return json_response(
            {
                "data": {
                    "flows": flows,
                    "stats": stats,
                    "synthesis": synthesis_data,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            }
        )

    async def _get_confidence_history(self, query_params: dict[str, Any]) -> HandlerResult:
        """Get confidence score changes over time for KM entries."""
        bridge = self._get_km_outcome_bridge()

        entries: list[dict[str, Any]] = []

        if bridge is not None:
            validations = getattr(bridge, "_validations_applied", [])

            # Group validations by KM item
            by_item: dict[str, list] = {}
            for v in validations:
                by_item.setdefault(v.km_item_id, []).append(v)

            for node_id, item_validations in by_item.items():
                history = []
                for v in item_validations:
                    history.append(
                        {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "value": round(v.new_confidence, 4),
                            "previous": round(v.original_confidence, 4),
                            "reason": (
                                "debate_outcome_boost"
                                if v.was_successful
                                else "debate_outcome_penalty"
                            ),
                            "debate_id": v.debate_id,
                        }
                    )

                content_preview = f"KM node {node_id}"
                entries.append(
                    {
                        "node_id": node_id,
                        "content_preview": content_preview,
                        "confidence_history": history,
                    }
                )

        return json_response(
            {
                "data": {
                    "entries": entries,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            }
        )

    async def _get_adapter_health(self) -> HandlerResult:
        """Get health status for all KM adapters."""
        adapters_info: list[dict[str, Any]] = []
        total = 0
        active = 0
        stale = 0
        offline = 0

        try:
            from aragora.knowledge.mound.adapters.factory import ADAPTER_SPECS

            total = len(ADAPTER_SPECS)

            for name, spec in ADAPTER_SPECS.items():
                adapter_info: dict[str, Any] = {
                    "name": name,
                    "status": "unknown",
                    "entry_count": 0,
                    "last_sync": None,
                    "health": "unknown",
                    "priority": spec.priority,
                    "enabled_by_default": spec.enabled_by_default,
                    "has_reverse_sync": spec.reverse_method is not None,
                }

                # Check if the adapter module is importable
                try:
                    module_path = None
                    for mod_path, cls_name, kwargs in _get_adapter_defs():
                        if kwargs.get("name") == name:
                            module_path = mod_path
                            break

                    if module_path:
                        importlib.import_module(
                            module_path,
                            package="aragora.knowledge.mound.adapters",
                        )
                        adapter_info["status"] = "available"
                        adapter_info["health"] = "healthy"
                        active += 1
                    else:
                        adapter_info["status"] = "registered"
                        adapter_info["health"] = "healthy"
                        active += 1

                except ImportError:
                    adapter_info["status"] = "unavailable"
                    adapter_info["health"] = "offline"
                    offline += 1
                except (RuntimeError, ValueError, OSError):
                    adapter_info["status"] = "error"
                    adapter_info["health"] = "stale"
                    stale += 1

                adapters_info.append(adapter_info)

        except ImportError:
            logger.warning("Adapter factory not available")

        # Sort by priority descending (highest priority first)
        adapters_info.sort(key=lambda a: a.get("priority", 0), reverse=True)

        return json_response(
            {
                "data": {
                    "adapters": adapters_info,
                    "total": total,
                    "active": active,
                    "stale": stale,
                    "offline": offline,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            }
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_km_outcome_bridge(self) -> Any:
        """Get the KMOutcomeBridge instance if available."""
        ctx = self.ctx or {}
        bridge = ctx.get("km_outcome_bridge")
        if bridge is not None:
            return bridge

        # Try to get from arena
        arena = ctx.get("arena")
        if arena is not None:
            return getattr(arena, "km_outcome_bridge", None)

        return None

    def _get_knowledge_injector(self) -> Any:
        """Get the DebateKnowledgeInjector if available."""
        try:
            from aragora.debate.knowledge_injection import DebateKnowledgeInjector

            ctx = self.ctx or {}
            injector = ctx.get("knowledge_injector")
            if injector is not None:
                return injector
            return DebateKnowledgeInjector()
        except ImportError:
            pass
        return None

    def _get_knowledge_mound(self) -> Any:
        """Get the KnowledgeMound instance if available."""
        try:
            ctx = self.ctx or {}
            mound = ctx.get("knowledge_mound")
            if mound is not None:
                return mound

            arena = ctx.get("arena")
            if arena is not None:
                return getattr(arena, "knowledge_mound", None)
        except (AttributeError, TypeError):
            pass
        return None


def _get_adapter_defs() -> list[tuple[str, str, dict[str, Any]]]:
    """Get the adapter definitions from the factory module."""
    try:
        from aragora.knowledge.mound.adapters.factory import _ADAPTER_DEFS

        return _ADAPTER_DEFS
    except ImportError:
        return []
