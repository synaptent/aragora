"""Canvas to Workflow synchronization.

Converts visual canvas graph state (UniversalGraph Stage 4 nodes)
into executable WorkflowDefinitions, ensuring canvas edits are
reflected in the actual workflow that gets executed.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Literal, cast
from typing import Any

logger = logging.getLogger(__name__)

_ORCH_TO_STEP = {
    "agent_task": "task",
    "debate": "debate",
    "human_gate": "human_checkpoint",
    "parallel_fan": "parallel",
    "merge": "merge",
    "verification": "verification",
}
_IMPLEMENT_STEP_TYPES = {"task", "implementation", "computer_use_task"}


@dataclass
class CanvasChange:
    """Describes a single diff between canvas and workflow state."""

    change_type: str  # 'added', 'removed', 'modified'
    node_id: str
    field: str
    old_value: Any = None
    new_value: Any = None


def sync_canvas_to_workflow(graph: Any) -> dict[str, Any]:
    """Convert Stage 4 (orchestration) nodes from a UniversalGraph into a WorkflowDefinition dict.

    Reads orchestration nodes, converts:
    - agent_task -> task StepDefinition
    - parallel_fan -> parallel StepDefinition
    - human_gate -> human_checkpoint StepDefinition
    - verification -> verification StepDefinition
    - debate -> debate StepDefinition
    - merge -> merge StepDefinition

    Edges between orchestration nodes become TransitionRules.

    Returns a dict matching WorkflowDefinition schema with 'steps' and 'transitions'.
    """
    pipeline_stage_orchestration = None
    try:
        from aragora.canvas.stages import PipelineStage

        pipeline_stage_orchestration = PipelineStage.ORCHESTRATION
    except ImportError:
        pass

    # Get orchestration nodes
    orch_nodes: dict[str, Any] = {}
    if hasattr(graph, "nodes"):
        for node_id, node in graph.nodes.items():
            stage = getattr(node, "stage", None)
            if stage and hasattr(stage, "value") and stage.value == "orchestration":
                orch_nodes[node_id] = node
            elif pipeline_stage_orchestration is not None and stage == pipeline_stage_orchestration:
                orch_nodes[node_id] = node

    return build_workflow_definition_from_orchestration(
        name=getattr(graph, "name", "Canvas Workflow"),
        workflow_id=f"wf-{getattr(graph, 'id', 'canvas')}",
        nodes=orch_nodes,
        edges=getattr(graph, "edges", {}),
        metadata={
            "source": "canvas_sync",
            "graph_id": getattr(graph, "id", ""),
            "node_count": len(orch_nodes),
        },
    )


def build_workflow_definition_from_orchestration(
    *,
    name: str,
    nodes: Any,
    edges: Any,
    workflow_id: str,
    description: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a WorkflowDefinition payload from orchestration nodes/edges."""
    steps: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    orch_nodes: dict[str, Any] = {}

    for fallback_id, node in _iter_items(nodes):
        node_id = _node_attr(node, "id", fallback_id)
        node_data = _node_data(node)
        orch_type = node_data.get("orchType", node_data.get("orch_type", "agent_task"))
        step_type = _ORCH_TO_STEP.get(str(orch_type), "task")
        config: dict[str, Any] = {
            "assigned_agent": node_data.get("assignedAgent", node_data.get("assigned_agent", "")),
            "capabilities": _string_list(node_data.get("capabilities")),
            "elo_score": node_data.get("eloScore", node_data.get("elo_score")),
        }
        agent_pool = node_data.get("agent_pool")
        if agent_pool:
            config["agent_pool"] = agent_pool
        files = node_data.get("files")
        if isinstance(files, list):
            config["files"] = [str(item) for item in files if str(item)]
        complexity = node_data.get("complexity")
        if complexity in {"simple", "moderate", "complex"}:
            config["complexity"] = complexity
        if node_data.get("requires_approval") is not None:
            config["requires_approval"] = bool(node_data.get("requires_approval"))

        step = {
            "id": node_id,
            "name": node_data.get("label", _node_attr(node, "label", f"Step {node_id}")),
            "description": node_data.get("description", ""),
            "step_type": step_type,
            "config": config,
            "timeout_seconds": node_data.get("timeoutSeconds", 3600),
            "retries": node_data.get("retries", 1),
            "optional": node_data.get("optional", False),
        }
        steps.append(step)
        orch_nodes[node_id] = node

    for fallback_id, edge in _iter_items(edges):
        source = _edge_attr(edge, "source_id", _edge_attr(edge, "source", ""))
        target = _edge_attr(edge, "target_id", _edge_attr(edge, "target", ""))
        if source in orch_nodes and target in orch_nodes:
            transitions.append(
                {
                    "id": _edge_attr(edge, "id", f"tr-{source}-{target}-{fallback_id}"),
                    "from_step": source,
                    "to_step": target,
                    "condition": _edge_attr(edge, "condition", ""),
                    "label": _edge_attr(edge, "label", ""),
                    "priority": 0,
                }
            )

    workflow_metadata = {
        "source": "canvas_sync",
        "node_count": len(steps),
    }
    if isinstance(metadata, dict):
        workflow_metadata.update(metadata)

    return {
        "id": workflow_id,
        "name": name,
        "description": description,
        "steps": steps,
        "transitions": transitions,
        "metadata": workflow_metadata,
    }


def workflow_definition_to_implement_plan(workflow_definition: dict[str, Any]) -> Any:
    """Derive a minimal ImplementPlan from a workflow definition."""
    from aragora.implement.types import ImplementPlan, ImplementTask

    steps = workflow_definition.get("steps", [])
    transitions = workflow_definition.get("transitions", [])
    task_step_ids = {
        str(step.get("id"))
        for step in steps
        if isinstance(step, dict) and step.get("step_type") in _IMPLEMENT_STEP_TYPES
    }
    deps: dict[str, list[str]] = {step_id: [] for step_id in task_step_ids}
    for transition in transitions:
        if not isinstance(transition, dict):
            continue
        source = str(transition.get("from_step", ""))
        target = str(transition.get("to_step", ""))
        if source in task_step_ids and target in deps and source not in deps[target]:
            deps[target].append(source)

    tasks: list[ImplementTask] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("id", ""))
        if step_id not in task_step_ids:
            continue
        config = step.get("config", {})
        if not isinstance(config, dict):
            config = {}
        files = config.get("files")
        if not isinstance(files, list):
            files = []
        complexity_value = str(config.get("complexity", "moderate"))
        if complexity_value not in {"simple", "moderate", "complex"}:
            complexity_value = "moderate"
        complexity = cast(Literal["simple", "moderate", "complex"], complexity_value)
        tasks.append(
            ImplementTask(
                id=step_id,
                description=str(step.get("description") or step.get("name") or step_id),
                files=[str(item) for item in files if str(item)],
                complexity=complexity,
                dependencies=deps.get(step_id, []),
                task_type=str(step.get("step_type", "task")),
                capabilities=_string_list(config.get("capabilities")),
                requires_approval=bool(config.get("requires_approval", False)),
            )
        )

    design_hash = hashlib.sha256(
        json.dumps(
            {
                "workflow_id": workflow_definition.get("id", ""),
                "task_steps": [task.id for task in tasks],
                "transitions": [
                    transition
                    for transition in transitions
                    if isinstance(transition, dict)
                    and transition.get("from_step") in task_step_ids
                    and transition.get("to_step") in task_step_ids
                ],
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return ImplementPlan(design_hash=design_hash, tasks=tasks)


def build_decision_plan_from_workflow_definition(
    workflow_definition: dict[str, Any],
    *,
    debate_id: str,
    task: str,
    metadata: dict[str, Any] | None = None,
) -> Any:
    """Create a DecisionPlan that preserves a workflow definition in metadata."""
    from copy import deepcopy

    from aragora.pipeline.decision_plan import ApprovalMode, DecisionPlanFactory, PlanStatus

    workflow_payload = deepcopy(workflow_definition)
    workflow_metadata = workflow_payload.get("metadata")
    if not isinstance(workflow_metadata, dict):
        workflow_metadata = {}
    workflow_payload["metadata"] = workflow_metadata

    plan = DecisionPlanFactory.from_implement_plan(
        workflow_definition_to_implement_plan(workflow_payload),
        debate_id=debate_id,
        task=task,
        implementation_profile={"execution_mode": "workflow"},
    )
    plan.approval_mode = ApprovalMode.NEVER
    plan.status = PlanStatus.CREATED
    combined_metadata: dict[str, Any] = {}
    if isinstance(metadata, dict):
        combined_metadata.update(metadata)
    combined_metadata["workflow_definition"] = workflow_payload
    combined_metadata.setdefault("execution_mode", "workflow")
    plan.metadata.update(combined_metadata)
    return plan


def diff_canvas_workflow(
    graph: Any,
    existing_workflow: dict[str, Any],
) -> list[CanvasChange]:
    """Compare canvas state against existing workflow and return changes.

    Useful for detecting what the user modified in the canvas since
    the workflow was last synced.
    """
    changes: list[CanvasChange] = []
    current = sync_canvas_to_workflow(graph)

    current_steps = {s["id"]: s for s in current.get("steps", [])}
    existing_steps = {s["id"]: s for s in existing_workflow.get("steps", [])}

    # Find added steps
    for step_id in current_steps:
        if step_id not in existing_steps:
            changes.append(
                CanvasChange(
                    change_type="added",
                    node_id=step_id,
                    field="step",
                    new_value=current_steps[step_id],
                )
            )

    # Find removed steps
    for step_id in existing_steps:
        if step_id not in current_steps:
            changes.append(
                CanvasChange(
                    change_type="removed",
                    node_id=step_id,
                    field="step",
                    old_value=existing_steps[step_id],
                )
            )

    # Find modified steps
    for step_id in current_steps:
        if step_id in existing_steps:
            curr = current_steps[step_id]
            prev = existing_steps[step_id]
            for key in ("name", "step_type", "config", "description"):
                if curr.get(key) != prev.get(key):
                    changes.append(
                        CanvasChange(
                            change_type="modified",
                            node_id=step_id,
                            field=key,
                            old_value=prev.get(key),
                            new_value=curr.get(key),
                        )
                    )

    return changes


def _iter_items(values: Any) -> list[tuple[str, Any]]:
    if isinstance(values, dict):
        return [(str(key), value) for key, value in values.items()]
    if isinstance(values, list):
        items: list[tuple[str, Any]] = []
        for index, value in enumerate(values):
            if isinstance(value, dict) and value.get("id"):
                items.append((str(value["id"]), value))
            else:
                items.append((str(index), value))
        return items
    return []


def _node_data(node: Any) -> dict[str, Any]:
    if isinstance(node, dict):
        data = node.get("data", {})
    else:
        data = getattr(node, "data", {})
    if isinstance(data, dict):
        return data
    if hasattr(data, "__dict__"):
        return dict(data.__dict__)
    return {}


def _node_attr(node: Any, attr: str, default: str) -> str:
    if isinstance(node, dict):
        value = node.get(attr, default)
    else:
        value = getattr(node, attr, default)
    return str(value or default)


def _edge_attr(edge: Any, attr: str, default: str) -> str:
    if isinstance(edge, dict):
        value = edge.get(attr, default)
    else:
        value = getattr(edge, attr, default)
    return str(value or default)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return []
