"""Auto-layout algorithms for workflow graphs.

Provides layout algorithms for positioning workflow steps on a visual
canvas. Used by the NL builder and visual builder API.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any


GRID_SNAP = 20  # Snap positions to 20px grid
NODE_WIDTH = 200
NODE_HEIGHT = 100
HORIZONTAL_GAP = 80
VERTICAL_GAP = 60

STEP_TYPE_TO_CATEGORY: dict[str, str] = {
    "agent": "agent",
    "parallel": "control",
    "conditional": "control",
    "loop": "control",
    "switch": "control",
    "decision": "control",
    "human_checkpoint": "human",
    "memory_read": "memory",
    "memory_write": "memory",
    "debate": "debate",
    "quick_debate": "debate",
    "task": "agent",
    "connector": "integration",
    "nomic": "agent",
    "nomic_loop": "agent",
    "implementation": "agent",
    "verification": "agent",
    "openclaw_action": "integration",
    "openclaw_session": "integration",
    "computer_use_task": "integration",
    "content_extraction": "extraction",
}


@dataclass
class NodePosition:
    """Position data for a workflow node."""

    step_id: str
    x: float
    y: float
    layer: int
    order: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "x": self.x,
            "y": self.y,
            "layer": self.layer,
            "order": self.order,
        }


def _snap_to_grid(value: float) -> float:
    """Snap a coordinate to the nearest grid point."""
    return round(value / GRID_SNAP) * GRID_SNAP


def _topological_sort(adj: dict[str, list[str]], nodes: list[str]) -> list[list[str]]:
    """Topological layer assignment using Kahn's algorithm.

    Returns a list of layers, each containing node IDs at that depth.
    """
    in_degree: dict[str, int] = dict.fromkeys(nodes, 0)
    for src in nodes:
        for dst in adj.get(src, []):
            if dst in in_degree:
                in_degree[dst] += 1

    queue: deque[str] = deque(n for n in nodes if in_degree[n] == 0)
    layers: list[list[str]] = []

    while queue:
        layer: list[str] = []
        for _ in range(len(queue)):
            node = queue.popleft()
            layer.append(node)
            for neighbor in adj.get(node, []):
                if neighbor in in_degree:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)
        layers.append(layer)

    # Add any remaining nodes (cycles) to the last layer
    placed = {n for layer in layers for n in layer}
    remaining = [n for n in nodes if n not in placed]
    if remaining:
        layers.append(remaining)

    return layers


def _barycenter_reorder(layers: list[list[str]], adj: dict[str, list[str]]) -> list[list[str]]:
    """Minimize edge crossings using the barycenter heuristic.

    Performs 4 iterations of forward/backward sweeps.
    """
    node_to_layer: dict[str, int] = {}
    node_to_order: dict[str, int] = {}
    for layer_idx, layer in enumerate(layers):
        for order, node in enumerate(layer):
            node_to_layer[node] = layer_idx
            node_to_order[node] = order

    # Build reverse adjacency
    rev_adj: dict[str, list[str]] = defaultdict(list)
    for src, dsts in adj.items():
        for dst in dsts:
            rev_adj[dst].append(src)

    for _iteration in range(4):
        # Forward sweep (top to bottom)
        for layer_idx in range(1, len(layers)):
            barycenters: dict[str, float] = {}
            for node in layers[layer_idx]:
                parents = [
                    p for p in rev_adj.get(node, []) if node_to_layer.get(p, -1) == layer_idx - 1
                ]
                if parents:
                    barycenters[node] = sum(node_to_order.get(p, 0) for p in parents) / len(parents)
                else:
                    barycenters[node] = float(node_to_order.get(node, 0))
            layers[layer_idx] = sorted(layers[layer_idx], key=lambda n: barycenters.get(n, 0))
            for order, node in enumerate(layers[layer_idx]):
                node_to_order[node] = order

        # Backward sweep (bottom to top)
        for layer_idx in range(len(layers) - 2, -1, -1):
            barycenters = {}
            for node in layers[layer_idx]:
                children = [
                    c for c in adj.get(node, []) if node_to_layer.get(c, -1) == layer_idx + 1
                ]
                if children:
                    barycenters[node] = sum(node_to_order.get(c, 0) for c in children) / len(
                        children
                    )
                else:
                    barycenters[node] = float(node_to_order.get(node, 0))
            layers[layer_idx] = sorted(layers[layer_idx], key=lambda n: barycenters.get(n, 0))
            for order, node in enumerate(layers[layer_idx]):
                node_to_order[node] = order

    return layers


def flow_layout(
    steps: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
) -> list[NodePosition]:
    """Compute DAG layout for workflow steps.

    Args:
        steps: List of dicts with at least ``{"id": str, "type": str}``.
        transitions: List of dicts with ``{"from_step": str, "to_step": str}``.

    Returns:
        List of NodePosition with computed coordinates.
    """
    if not steps:
        return []

    nodes = [s["id"] for s in steps]
    adj: dict[str, list[str]] = defaultdict(list)
    for t in transitions:
        from_id = t.get("from_step", "")
        to_id = t.get("to_step", "")
        if from_id and to_id:
            adj[from_id].append(to_id)

    # Layer assignment via topological sort
    layers = _topological_sort(adj, nodes)

    # Minimize crossings
    layers = _barycenter_reorder(layers, adj)

    # Compute positions
    positions: list[NodePosition] = []
    for layer_idx, layer in enumerate(layers):
        for order, node_id in enumerate(layer):
            x = _snap_to_grid(order * (NODE_WIDTH + HORIZONTAL_GAP))
            y = _snap_to_grid(layer_idx * (NODE_HEIGHT + VERTICAL_GAP))
            positions.append(
                NodePosition(
                    step_id=node_id,
                    x=x,
                    y=y,
                    layer=layer_idx,
                    order=order,
                )
            )

    return positions


def grid_layout(
    steps: list[dict[str, Any]],
    columns: int = 3,
) -> list[NodePosition]:
    """Simple grid layout placing steps left-to-right, top-to-bottom.

    Args:
        steps: List of dicts with at least ``{"id": str}``.
        columns: Number of columns in the grid.

    Returns:
        List of NodePosition with computed coordinates.
    """
    if not steps:
        return []

    positions: list[NodePosition] = []
    for idx, step in enumerate(steps):
        col = idx % columns
        row = idx // columns
        x = _snap_to_grid(col * (NODE_WIDTH + HORIZONTAL_GAP))
        y = _snap_to_grid(row * (NODE_HEIGHT + VERTICAL_GAP))
        positions.append(
            NodePosition(
                step_id=step["id"],
                x=x,
                y=y,
                layer=row,
                order=col,
            )
        )

    return positions
