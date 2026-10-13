"""
Visualization endpoint handlers — argument cartography and replay.

Endpoints:
    GET  /api/v1/visualization/debates/{id}/graph       - Get argument graph for a debate
    GET  /api/v1/visualization/debates/{id}/mermaid      - Get Mermaid diagram
    GET  /api/v1/visualization/debates/{id}/html         - Get interactive HTML export
    GET  /api/v1/visualization/debates/{id}/statistics   - Get graph statistics
    POST /api/v1/visualization/debates/{id}/replay       - Generate replay artifact
"""

from __future__ import annotations

__all__ = [
    "VisualizationHandler",
]

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from aragora.rbac.decorators import require_permission
from aragora.utils.optional_imports import try_import

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter (30 req/min — graph operations are read-heavy)
_viz_limiter = RateLimiter(requests_per_minute=30)

# Optional imports
_mapper_imports, MAPPER_AVAILABLE = try_import(
    "aragora.visualization.mapper", "ArgumentCartographer"
)
ArgumentCartographer = _mapper_imports.get("ArgumentCartographer")

_replay_imports, REPLAY_AVAILABLE = try_import("aragora.visualization.replay", "ReplayGenerator")
ReplayGenerator = _replay_imports.get("ReplayGenerator")


class VisualizationHandler(BaseHandler):
    """Handler for argument visualization and replay endpoints."""

    def __init__(self, ctx: dict | None = None):
        self.ctx = ctx or {}

    ROUTES = [
        "/api/v1/visualization/debates",
    ]

    ROUTE_PREFIXES = [
        "/api/v1/visualization/debates/",
    ]

    def can_handle(self, path: str) -> bool:
        if path in self.ROUTES:
            return True
        return any(path.startswith(prefix) for prefix in self.ROUTE_PREFIXES)

    @require_permission("debates:read")
    def handle(self, path: str, query_params: dict, handler: Any = None) -> HandlerResult | None:
        """Route GET requests."""
        client_ip = get_client_ip(handler)
        if not _viz_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded. Please try again later.", 429)

        if not MAPPER_AVAILABLE:
            return error_response("Visualization module not available", 503)

        # /api/v1/visualization/debates/{id}/graph
        if path.endswith("/graph"):
            debate_id = self.extract_path_param(path, 4, "debate_id")
            include_full = query_params.get("include_full_content", "false").lower() == "true"
            return self._get_graph(debate_id, include_full)

        # /api/v1/visualization/debates/{id}/mermaid
        if path.endswith("/mermaid"):
            debate_id = self.extract_path_param(path, 4, "debate_id")
            direction = query_params.get("direction", "TD")
            return self._get_mermaid(debate_id, direction)

        # /api/v1/visualization/debates/{id}/html
        if path.endswith("/html"):
            debate_id = self.extract_path_param(path, 4, "debate_id")
            title = query_params.get("title", "Debate Argument Map")
            return self._get_html(debate_id, title)

        # /api/v1/visualization/debates/{id}/statistics
        if path.endswith("/statistics"):
            debate_id = self.extract_path_param(path, 4, "debate_id")
            return self._get_statistics(debate_id)

        return None

    @handle_errors("replay generation")
    @require_permission("debates:read")
    def handle_post(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route POST requests."""
        client_ip = get_client_ip(handler)
        if not _viz_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded. Please try again later.", 429)

        # /api/v1/visualization/debates/{id}/replay
        if path.endswith("/replay"):
            debate_id = self.extract_path_param(path, 4, "debate_id")
            body = self.read_json_body(handler) or {}
            return self._generate_replay(debate_id, body)

        return None

    @handle_errors("argument graph retrieval")
    def _get_graph(self, debate_id: str, include_full: bool) -> HandlerResult:
        """Get the argument graph for a debate."""
        graph = self._build_graph(debate_id)
        if graph is None:
            return error_response("Failed to build argument graph", 404)

        return json_response(graph.to_dict())

    @handle_errors("mermaid export")
    def _get_mermaid(self, debate_id: str, direction: str) -> HandlerResult:
        """Get Mermaid diagram for a debate."""
        if direction not in ("TD", "LR", "BT", "RL"):
            direction = "TD"

        graph = self._build_graph(debate_id)
        if graph is None:
            return error_response("Failed to build argument graph", 404)

        mermaid = graph.export_mermaid(direction=direction)
        return json_response({"debate_id": debate_id, "direction": direction, "mermaid": mermaid})

    @handle_errors("html export")
    def _get_html(self, debate_id: str, title: str) -> HandlerResult:
        """Get interactive HTML export for a debate."""
        graph = self._build_graph(debate_id)
        if graph is None:
            return error_response("Failed to build argument graph", 404)

        html = graph.export_html(title=title)
        return json_response({"debate_id": debate_id, "html": html})

    @handle_errors("statistics retrieval")
    def _get_statistics(self, debate_id: str) -> HandlerResult:
        """Get graph statistics for a debate."""
        graph = self._build_graph(debate_id)
        if graph is None:
            return error_response("Failed to build argument graph", 404)

        stats = graph.get_statistics()
        return json_response({"debate_id": debate_id, **stats})

    @handle_errors("replay generation")
    def _generate_replay(self, debate_id: str, options: dict) -> HandlerResult:
        """Generate a replay artifact for a debate."""
        if not REPLAY_AVAILABLE or not ReplayGenerator:
            return error_response("Replay module not available", 503)

        graph = self._build_graph(debate_id)
        if graph is None:
            return error_response("Failed to build argument graph", 404)

        generator = ReplayGenerator()
        artifact = generator.generate(
            graph,
            **{k: v for k, v in options.items() if k in ("fps", "duration", "highlight_consensus")},
        )

        return json_response(
            {
                "debate_id": debate_id,
                "scenes": [s.to_dict() for s in artifact.scenes]
                if hasattr(artifact, "scenes")
                else [],
                "metadata": artifact.metadata if hasattr(artifact, "metadata") else {},
            }
        )

    def _build_graph(self, debate_id: str) -> Any:
        """Build argument graph from debate messages.

        Loads debate data from store and constructs the ArgumentCartographer graph.
        """
        if not ArgumentCartographer:
            return None

        # Load debate result from store
        debate_result = self._load_debate(debate_id)
        if debate_result is None:
            return None

        graph = ArgumentCartographer()
        topic = getattr(debate_result, "topic", debate_id)
        graph.set_debate_context(debate_id, str(topic))

        messages = getattr(debate_result, "messages", [])
        if isinstance(messages, list):
            for msg in messages:
                agent = str(getattr(msg, "agent", "unknown"))
                content = str(getattr(msg, "content", ""))
                role = str(getattr(msg, "role", "proposal"))
                round_num = int(getattr(msg, "round", 0) or 0)
                if content:
                    graph.update_from_message(
                        agent=agent,
                        content=content,
                        role=role,
                        round_num=round_num,
                    )

        return graph if graph.nodes else None

    def _load_debate(self, debate_id: str) -> Any:
        """Load debate result from available stores."""
        # Try receipt store first
        try:
            from aragora.gauntlet.receipts import get_receipt_store

            store = get_receipt_store()
            receipt = store.get(debate_id)
            if receipt and hasattr(receipt, "debate_result"):
                return receipt.debate_result
        except (ImportError, AttributeError, KeyError):
            pass

        # Try consensus store
        try:
            from aragora.memory.consensus import ConsensusStore

            cs = ConsensusStore()
            result = cs.get(debate_id)  # type: ignore[attr-defined]
            if result:
                return result
        except (ImportError, AttributeError, KeyError):
            pass

        logger.debug("No debate found for visualization: %s", debate_id)
        return None
