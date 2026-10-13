"""Pipeline Telemetry REST Handler.

Exposes stage timing metrics from the pipeline's stage transition system.

Endpoints:
- GET /api/v1/pipeline/telemetry  - Stage timing metrics
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.server.handlers.base import HandlerResult, error_response, handle_errors, json_response

logger = logging.getLogger(__name__)


def _get_store() -> Any:
    """Lazy-load the GraphStore singleton."""
    from aragora.pipeline.graph_store import get_graph_store

    return get_graph_store()


class PipelineTelemetryHandler:
    """HTTP handler for pipeline stage telemetry."""

    ROUTES = [
        "GET /api/v1/pipeline/telemetry",
    ]

    def __init__(self, ctx: dict[str, Any] | None = None) -> None:
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        return path in ("/api/v1/pipeline/telemetry", "/api/pipeline/telemetry")

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> Any:
        """Dispatch GET requests."""
        if not self.can_handle(path):
            return None
        return self._handle_get_telemetry()

    @handle_errors("pipeline telemetry")
    def _handle_get_telemetry(self) -> HandlerResult:
        """GET /api/v1/pipeline/telemetry

        Returns stage timing metrics aggregated from recorded transitions.
        """
        try:
            stages = _collect_stage_metrics()

            return json_response({"data": {"stages": stages}})
        except ImportError as e:
            logger.warning("Pipeline telemetry unavailable: %s", e)
            return error_response("Pipeline telemetry unavailable", 500)


def _collect_stage_metrics() -> list[dict[str, Any]]:
    """Collect per-stage metrics from the graph store's transitions.

    Scans all graphs for recorded StageTransitions and computes
    count, average confidence, and status breakdown per stage pair.
    """
    from aragora.canvas.stages import PipelineStage

    stage_order = [
        PipelineStage.IDEAS,
        PipelineStage.GOALS,
        PipelineStage.ACTIONS,
        PipelineStage.ORCHESTRATION,
    ]

    # Try to read transitions from the graph store
    transitions: list[Any] = []
    try:
        store = _get_store()
        for graph in store.list():
            graph_obj = store.get(graph["id"] if isinstance(graph, dict) else graph.id)
            if graph_obj and hasattr(graph_obj, "transitions"):
                transitions.extend(graph_obj.transitions)
    except (ImportError, OSError, TypeError, AttributeError):
        pass

    # Build per-stage-pair aggregates
    pair_stats: dict[str, dict[str, Any]] = {}
    for t in transitions:
        from_val = t.from_stage.value if hasattr(t.from_stage, "value") else str(t.from_stage)
        to_val = t.to_stage.value if hasattr(t.to_stage, "value") else str(t.to_stage)
        key = f"{from_val}->{to_val}"
        if key not in pair_stats:
            pair_stats[key] = {
                "from_stage": from_val,
                "to_stage": to_val,
                "count": 0,
                "total_confidence": 0.0,
                "statuses": {},
            }
        stats = pair_stats[key]
        stats["count"] += 1
        stats["total_confidence"] += getattr(t, "confidence", 0.0)
        status = getattr(t, "status", "unknown")
        stats["statuses"][status] = stats["statuses"].get(status, 0) + 1

    # Format output
    stages: list[dict[str, Any]] = []
    for key, stats in pair_stats.items():
        count = stats["count"]
        stages.append(
            {
                "from_stage": stats["from_stage"],
                "to_stage": stats["to_stage"],
                "transition_count": count,
                "avg_confidence": round(stats["total_confidence"] / count, 3) if count else 0.0,
                "statuses": stats["statuses"],
            }
        )

    # If no transitions exist yet, return the stage skeleton so the
    # frontend always has something to render.
    if not stages:
        for i in range(len(stage_order) - 1):
            stages.append(
                {
                    "from_stage": stage_order[i].value,
                    "to_stage": stage_order[i + 1].value,
                    "transition_count": 0,
                    "avg_confidence": 0.0,
                    "statuses": {},
                }
            )

    return stages
