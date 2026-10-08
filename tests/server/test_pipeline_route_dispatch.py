"""Which handler serves each legacy pipeline route.

The server resolves a path through ``RouteIndex`` and, when the index has no
match, asks each registered handler's ``can_handle`` in registry order. These
tests reproduce both steps with the real handler classes and registry attr
names (``RouteIndex.build()`` keys its prefix patterns by attr name).

Pins the routing behind the owner 403/500 on canvas pipeline routes:
``CanvasHandler`` claimed every ``/api/v1/canvas/*`` path, and
``CanvasPipelineHandler`` claimed every ``/api/v1/pipeline/*`` path ahead of
the execute and DAG handlers.
"""

from __future__ import annotations

from typing import Any

import pytest

from aragora.server.handler_registry import HANDLER_REGISTRY, RouteIndex
from aragora.server.handlers.canvas import CanvasHandler
from aragora.server.handlers.canvas.canvas_pipeline import CanvasPipelineHandler
from aragora.server.handlers.pipeline.dag_operations import DAGOperationsHandler
from aragora.server.handlers.pipeline.execute import PipelineExecuteHandler
from aragora.server.handlers.pipeline.transitions import PipelineTransitionsHandler
from aragora.server.handlers.pipeline.universal_graph import UniversalGraphHandler

_SUBSET = [
    ("_canvas_handler", CanvasHandler),
    ("_canvas_pipeline_handler", CanvasPipelineHandler),
    ("_universal_graph_handler", UniversalGraphHandler),
    ("_pipeline_transitions_handler", PipelineTransitionsHandler),
    ("_dag_operations_handler", DAGOperationsHandler),
    ("_pipeline_execute_handler", PipelineExecuteHandler),
]


def _registry_position(attr_name: str) -> int:
    for i, (name, _entry) in enumerate(HANDLER_REGISTRY):
        if name == attr_name:
            return i
    raise AssertionError(f"{attr_name} not found in HANDLER_REGISTRY")


def test_subset_preserves_real_registry_order() -> None:
    positions = [_registry_position(name) for name, _ in _SUBSET]
    assert positions == sorted(positions)


class _Registry:
    def __init__(self) -> None:
        for attr_name, handler_cls in _SUBSET:
            setattr(self, attr_name, handler_cls({}))


@pytest.fixture()
def resolve():
    registry = _Registry()
    index = RouteIndex()
    index.build(registry, _SUBSET)

    def _resolve(path: str) -> str | None:
        match: Any = index.get_handler(path)
        if match is not None:
            return match[0]
        for attr_name, _cls in _SUBSET:
            if getattr(registry, attr_name).can_handle(path):
                return attr_name
        return None

    return _resolve


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/v1/canvas/pipeline", "_canvas_pipeline_handler"),
        ("/api/v1/canvas/pipeline/templates", "_canvas_pipeline_handler"),
        ("/api/v1/canvas/pipeline/pipe-1", "_canvas_pipeline_handler"),
        ("/api/v1/canvas/pipeline/pipe-1/status", "_canvas_pipeline_handler"),
        ("/api/v1/canvas/pipeline/pipe-1/intelligence", "_canvas_pipeline_handler"),
        ("/api/v1/canvas/pipeline/from-ideas", "_canvas_pipeline_handler"),
        ("/api/v1/canvas/convert/debate", "_canvas_pipeline_handler"),
        ("/api/v1/pipeline/pipe-1/agents", "_canvas_pipeline_handler"),
        ("/api/v1/pipeline/pipe-1/agents/agent-1/approve", "_canvas_pipeline_handler"),
        ("/api/v1/canvas", "_canvas_handler"),
        ("/api/v1/canvas/canvas-1", "_canvas_handler"),
        ("/api/v1/canvas/canvas-1/nodes", "_canvas_handler"),
        ("/api/v1/pipeline/pipe-1/execute", "_pipeline_execute_handler"),
        ("/api/v1/pipeline/dag/graph-1", "_dag_operations_handler"),
        ("/api/v1/pipeline/dag/graph-1/nodes/n1/debate", "_dag_operations_handler"),
        ("/api/v1/pipeline/dag/graph-1/auto-flow", "_dag_operations_handler"),
        ("/api/v1/pipeline/transitions/ideas-to-goals", "_pipeline_transitions_handler"),
        ("/api/v1/pipeline/graphs/graph-1", "_universal_graph_handler"),
    ],
)
def test_pipeline_routes_reach_their_handler(resolve, path: str, expected: str) -> None:
    assert resolve(path) == expected
