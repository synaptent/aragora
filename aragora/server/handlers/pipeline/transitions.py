"""
AI-powered stage transition endpoints for the idea-to-execution pipeline.

Provides:
  POST /api/v1/pipeline/transitions/ideas-to-goals
  POST /api/v1/pipeline/transitions/goals-to-tasks
  POST /api/v1/pipeline/transitions/tasks-to-workflow
  POST /api/v1/pipeline/transitions/execute
  GET  /api/v1/pipeline/transitions/:node_id/provenance
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, cast

from aragora.server.versioning.compat import strip_version_prefix

from ..base import (
    SAFE_ID_PATTERN,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
    validate_path_segment,
)
from ..secure import SecureHandler
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

_transition_limiter = RateLimiter(requests_per_minute=30)

# Valid mode values for transition endpoints
VALID_MODES = ("quick", "debate", "heuristic")


def _extract_mode(query_params: dict[str, Any]) -> str:
    """Extract and validate the ``mode`` query parameter.

    Returns ``"quick"`` when the parameter is absent or empty (backward-compat).
    Raises ``ValueError`` for unrecognised values.
    """
    raw = query_params.get("mode", "quick")
    # query_params may wrap values in a list (e.g. from urllib.parse.parse_qs)
    if isinstance(raw, list):
        raw = raw[0] if raw else "quick"
    mode = str(raw).lower().strip()
    if mode not in VALID_MODES:
        raise ValueError(f"Invalid mode '{mode}'. Must be one of: {', '.join(VALID_MODES)}")
    return mode


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class PipelineNode:
    """A node in the pipeline DAG spanning idea -> orchestration."""

    id: str
    stage: str  # "idea", "goal", "action", "orchestration"
    label: str
    metadata: dict[str, Any] = field(default_factory=dict)
    derived_from: list[str] = field(default_factory=list)
    hash: str = ""

    def __post_init__(self) -> None:
        if not self.hash:
            content = json.dumps(
                {
                    "id": self.id,
                    "stage": self.stage,
                    "label": self.label,
                    "metadata": self.metadata,
                },
                sort_keys=True,
            )
            self.hash = hashlib.sha256(content.encode()).hexdigest()[:16]


@dataclass
class PipelineEdge:
    """A directed edge between pipeline nodes."""

    source: str
    target: str
    edge_type: str  # "inspires", "derives", "decomposes", "triggers", "depends_on"


@dataclass
class TransitionResult:
    """Result of a stage transition."""

    nodes: list[PipelineNode]
    edges: list[PipelineEdge]
    provenance: dict[str, Any] = field(default_factory=dict)


# In-memory store keyed by node id (production would use DB)
_node_store: dict[str, dict[str, Any]] = {}


def get_node_store() -> dict[str, dict[str, Any]]:
    """Return the node store (allows test injection)."""
    return _node_store


# ---------------------------------------------------------------------------
# Transition logic helpers
# ---------------------------------------------------------------------------

_ASSIGNEE_TYPES = ["researcher", "implementer", "reviewer"]


def _cluster_ideas(ideas: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group ideas by simple keyword overlap clustering."""
    if not ideas:
        return []
    if len(ideas) <= 2:
        return [ideas]

    clusters: list[list[dict[str, Any]]] = []
    assigned: set[int] = set()

    for i, idea in enumerate(ideas):
        if i in assigned:
            continue
        cluster = [idea]
        assigned.add(i)
        words_i = set((idea.get("label") or idea.get("text", "")).lower().split())
        for j in range(i + 1, len(ideas)):
            if j in assigned:
                continue
            words_j = set((ideas[j].get("label") or ideas[j].get("text", "")).lower().split())
            if words_i & words_j:
                cluster.append(ideas[j])
                assigned.add(j)
        clusters.append(cluster)
    return clusters


def _ideas_to_goals_logic(
    ideas: list[dict[str, Any]],
    context: str | None = None,
    mode: str = "quick",
) -> TransitionResult:
    """Cluster ideas by topic similarity and extract goals.

    Args:
        ideas: List of idea dicts with at least ``label`` or ``text``.
        context: Optional freeform context string.
        mode: Transition mode -- ``"quick"`` (default, MetaPlanner heuristic),
              ``"debate"`` (full debate via MetaPlanner), or ``"heuristic"``
              (pure keyword clustering, no LLM).

    Tries LLM-powered goal derivation via MetaPlanner first, falling back
    to keyword-overlap clustering when MetaPlanner is unavailable or when
    ``mode="heuristic"``.
    """
    # ── Build idea nodes (shared by both LLM and heuristic paths) ──────
    idea_nodes: list[PipelineNode] = []
    idea_node_ids: list[str] = []
    for idea in ideas:
        idea_id = idea.get("id") or f"idea-{uuid.uuid4().hex[:8]}"
        idea_node = PipelineNode(
            id=idea_id,
            stage="idea",
            label=idea.get("label") or idea.get("text", "Untitled idea"),
            metadata=idea.get("metadata", {}),
        )
        idea_nodes.append(idea_node)
        idea_node_ids.append(idea_id)
        _node_store[idea_id] = asdict(idea_node)

    # ── Try LLM-powered goal derivation via MetaPlanner ────────────────
    if mode != "heuristic":
        try:
            from aragora.nomic.meta_planner import MetaPlanner, MetaPlannerConfig
            import asyncio

            planner = MetaPlanner(
                MetaPlannerConfig(
                    quick_mode=(mode == "quick"),
                    use_business_context=True,
                    max_goals=max(3, len(ideas) // 2),
                )
            )

            idea_summaries = [
                idea.get("label", idea.get("content", idea.get("text", ""))) for idea in ideas
            ]
            objective = (
                f"Derive actionable goals from these ideas: {'; '.join(idea_summaries[:10])}"
            )

            loop = asyncio.new_event_loop()
            try:
                prioritized_goals = loop.run_until_complete(
                    planner.prioritize_work(objective=objective)
                )
            finally:
                loop.close()

            if prioritized_goals:
                result_nodes: list[PipelineNode] = list(idea_nodes)
                result_edges: list[PipelineEdge] = []
                for pg in prioritized_goals:
                    goal_node = PipelineNode(
                        id=f"goal-{pg.id}" if not pg.id.startswith("goal-") else pg.id,
                        stage="goal",
                        label=pg.description,
                        metadata={
                            "objective": pg.description,
                            "key_results": pg.focus_areas,
                            "priority": pg.priority,
                            "rationale": pg.rationale,
                            "estimated_impact": pg.estimated_impact,
                            "context": context or "",
                        },
                        derived_from=idea_node_ids,
                    )
                    result_nodes.append(goal_node)
                    _node_store[goal_node.id] = asdict(goal_node)
                    for idea_n in idea_nodes:
                        result_edges.append(
                            PipelineEdge(
                                source=idea_n.id,
                                target=goal_node.id,
                                edge_type="derives",
                            )
                        )

                goal_nodes = [n for n in result_nodes if n.stage == "goal"]
                provenance_method = "meta_planner" if mode == "quick" else "meta_planner_debate"
                return TransitionResult(
                    nodes=result_nodes,
                    edges=result_edges,
                    provenance={
                        "method": provenance_method,
                        "mode": mode,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source_count": len(ideas),
                        "output_count": len(goal_nodes),
                    },
                )
        except (ImportError, RuntimeError, Exception) as e:
            logger.debug("MetaPlanner unavailable, using heuristic: %s", e)

    # ── Heuristic fallback: keyword-overlap clustering ─────────────────
    clusters = _cluster_ideas(ideas)

    nodes: list[PipelineNode] = list(idea_nodes)
    edges: list[PipelineEdge] = []

    for cluster in clusters:
        cluster_labels = [i.get("label") or i.get("text", "") for i in cluster]
        objective = f"Achieve: {cluster_labels[0]}" if cluster_labels else "Achieve: goal"
        goal_id = f"goal-{uuid.uuid4().hex[:8]}"
        source_ids = [i.get("id") or f"idea-{uuid.uuid4().hex[:8]}" for i in cluster]

        goal_node = PipelineNode(
            id=goal_id,
            stage="goal",
            label=objective,
            metadata={
                "objective": objective,
                "key_results": cluster_labels,
                "context": context or "",
            },
            derived_from=source_ids,
        )
        nodes.append(goal_node)
        _node_store[goal_id] = asdict(goal_node)

        for src in source_ids:
            edges.append(PipelineEdge(source=src, target=goal_id, edge_type="derives"))

    return TransitionResult(
        nodes=nodes,
        edges=edges,
        provenance={
            "method": "keyword_clustering",
            "mode": mode,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_count": len(ideas),
            "output_count": len(clusters),
        },
    )


def _goals_to_tasks_logic(
    goals: list[dict[str, Any]],
    max_tasks: int | None = None,
    mode: str = "quick",
) -> TransitionResult:
    """Decompose goals into actionable tasks.

    Args:
        goals: List of goal dicts with at least ``label``.
        max_tasks: Optional cap on total tasks generated.
        mode: Transition mode -- ``"quick"`` (default, heuristic TaskDecomposer),
              ``"debate"`` (debate-based decomposition), or ``"heuristic"``
              (pure key-result splitting, no LLM).

    Tries LLM-powered decomposition via TaskDecomposer first, falling back
    to heuristic key-result splitting when TaskDecomposer is unavailable or
    when ``mode="heuristic"``.
    """
    # Ensure all goals are stored
    for goal in goals:
        goal_id = goal.get("id") or f"goal-{uuid.uuid4().hex[:8]}"
        if goal_id not in _node_store:
            goal_node = PipelineNode(
                id=goal_id,
                stage="goal",
                label=goal.get("label", ""),
                metadata=goal.get("metadata", {}),
            )
            _node_store[goal_id] = asdict(goal_node)

    # ── Try LLM-powered decomposition via TaskDecomposer ───────────────
    if mode != "heuristic":
        try:
            from aragora.nomic.task_decomposer import TaskDecomposer, DecomposerConfig
            import asyncio

            decomposer = TaskDecomposer(DecomposerConfig(max_depth=1))

            all_nodes: list[PipelineNode] = []
            all_edges: list[PipelineEdge] = []
            task_count = 0

            for goal in goals:
                goal_id = goal.get("id") or f"goal-{uuid.uuid4().hex[:8]}"
                goal_text = goal.get("label", goal.get("content", ""))

                if mode == "debate":
                    # Full debate-based decomposition (async)
                    loop = asyncio.new_event_loop()
                    try:
                        decomposition = loop.run_until_complete(
                            decomposer.analyze_with_debate(goal_text)
                        )
                    finally:
                        loop.close()
                else:
                    # quick mode: heuristic-based analysis
                    decomposition = decomposer.analyze(goal_text)

                for idx, subtask in enumerate(decomposition.subtasks):
                    if max_tasks and task_count >= max_tasks:
                        break
                    task_id = (
                        f"task-{subtask.id}" if not subtask.id.startswith("task-") else subtask.id
                    )
                    assignee_type = _ASSIGNEE_TYPES[idx % len(_ASSIGNEE_TYPES)]

                    task_node = PipelineNode(
                        id=task_id,
                        stage="action",
                        label=subtask.title,
                        metadata={
                            "assignee_type": assignee_type,
                            "priority": "high" if idx == 0 else "medium",
                            "estimated_effort": subtask.estimated_complexity,
                            "source_goal_id": goal_id,
                            "description": subtask.description,
                            "file_scope": subtask.file_scope,
                        },
                        derived_from=[goal_id],
                    )
                    all_nodes.append(task_node)
                    _node_store[task_id] = asdict(task_node)
                    all_edges.append(
                        PipelineEdge(
                            source=goal_id,
                            target=task_id,
                            edge_type="decomposes",
                        )
                    )
                    task_count += 1

                if max_tasks and task_count >= max_tasks:
                    break

            if all_nodes:
                # Add dependency edges between sequential tasks of the same goal
                goal_tasks: dict[str, list[str]] = {}
                for node in all_nodes:
                    gid = node.metadata.get("source_goal_id", "")
                    if gid:
                        goal_tasks.setdefault(gid, []).append(node.id)
                for task_ids in goal_tasks.values():
                    for i in range(len(task_ids) - 1):
                        all_edges.append(
                            PipelineEdge(
                                source=task_ids[i],
                                target=task_ids[i + 1],
                                edge_type="depends_on",
                            )
                        )

                provenance_method = (
                    "task_decomposer_debate" if mode == "debate" else "task_decomposer"
                )
                return TransitionResult(
                    nodes=all_nodes,
                    edges=all_edges,
                    provenance={
                        "method": provenance_method,
                        "mode": mode,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source_count": len(goals),
                        "output_count": len(all_nodes),
                    },
                )
        except (ImportError, RuntimeError, Exception) as e:
            logger.debug("TaskDecomposer unavailable, using heuristic: %s", e)

    # ── Heuristic fallback: key-result splitting ───────────────────────
    nodes: list[PipelineNode] = []
    edges: list[PipelineEdge] = []
    task_count = 0

    for goal in goals:
        goal_id = goal.get("id") or f"goal-{uuid.uuid4().hex[:8]}"

        key_results = goal.get("metadata", {}).get("key_results", [])
        if not key_results:
            key_results = [goal.get("label", "Task")]

        # Create 1 task per key result, up to 5 per goal
        for idx, kr in enumerate(key_results[:5]):
            if max_tasks and task_count >= max_tasks:
                break
            task_id = f"task-{uuid.uuid4().hex[:8]}"
            assignee_type = _ASSIGNEE_TYPES[idx % len(_ASSIGNEE_TYPES)]

            task_node = PipelineNode(
                id=task_id,
                stage="action",
                label=kr if isinstance(kr, str) else str(kr),
                metadata={
                    "assignee_type": assignee_type,
                    "priority": "high" if idx == 0 else "medium",
                    "estimated_effort": "medium",
                    "source_goal_id": goal_id,
                },
                derived_from=[goal_id],
            )
            nodes.append(task_node)
            _node_store[task_id] = asdict(task_node)
            edges.append(PipelineEdge(source=goal_id, target=task_id, edge_type="decomposes"))
            task_count += 1

        if max_tasks and task_count >= max_tasks:
            break

    # Add dependency edges between sequential tasks of the same goal
    goal_tasks_heuristic: dict[str, list[str]] = {}
    for node in nodes:
        gid = node.metadata.get("source_goal_id", "")
        if gid:
            goal_tasks_heuristic.setdefault(gid, []).append(node.id)
    for task_ids in goal_tasks_heuristic.values():
        for i in range(len(task_ids) - 1):
            edges.append(
                PipelineEdge(source=task_ids[i], target=task_ids[i + 1], edge_type="depends_on")
            )

    return TransitionResult(
        nodes=nodes,
        edges=edges,
        provenance={
            "method": "heuristic_decomposition",
            "mode": mode,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_count": len(goals),
            "output_count": len(nodes),
        },
    )


def _tasks_to_workflow_logic(
    tasks: list[dict[str, Any]],
    execution_mode: str | None = None,
) -> TransitionResult:
    """Generate a workflow DAG from tasks.

    Tries creating a real WorkflowDefinition via the WorkflowEngine first,
    falling back to manual DAG generation when the engine is unavailable.
    """
    agent_map = {
        "researcher": "research_agent",
        "implementer": "code_agent",
        "reviewer": "review_agent",
    }

    # ── Try real WorkflowDefinition via WorkflowEngine ─────────────────
    try:
        from aragora.workflow.types import StepDefinition, WorkflowDefinition

        steps: list[StepDefinition] = []
        for idx, task in enumerate(tasks):
            task_id = task.get("id") or f"task-{uuid.uuid4().hex[:8]}"
            assignee = task.get("metadata", {}).get("assignee_type", "implementer")
            step = StepDefinition(
                id=f"step-{task_id}",
                name=task.get("label", f"Step {idx + 1}"),
                step_type=agent_map.get(assignee, "agent"),
                config={
                    "description": task.get("label", ""),
                    "source_task_id": task_id,
                },
            )
            steps.append(step)

        workflow = WorkflowDefinition(
            id=f"wf-{uuid.uuid4().hex[:8]}",
            name="pipeline-generated",
            description="Auto-generated from pipeline tasks",
            steps=steps,
        )

        # Convert WorkflowDefinition steps back to PipelineNodes so the
        # response format stays consistent with the heuristic path.
        nodes: list[PipelineNode] = []
        edges: list[PipelineEdge] = []

        for step in workflow.steps:
            source_task_id = step.config.get("source_task_id", "")
            orch_id = f"orch-{uuid.uuid4().hex[:8]}"
            orch_node = PipelineNode(
                id=orch_id,
                stage="orchestration",
                label=step.name,
                metadata={
                    "agent_type": step.step_type,
                    "execution_mode": execution_mode or "parallel",
                    "source_task_id": source_task_id,
                    "workflow_id": workflow.id,
                    "step_id": step.id,
                },
                derived_from=[source_task_id] if source_task_id else [],
            )
            nodes.append(orch_node)
            _node_store[orch_id] = asdict(orch_node)
            if source_task_id:
                edges.append(
                    PipelineEdge(
                        source=source_task_id,
                        target=orch_id,
                        edge_type="triggers",
                    )
                )

        # Carry over sequential dependency edges
        orch_by_task: dict[str, str] = {}
        for node in nodes:
            src = node.metadata.get("source_task_id", "")
            if src:
                orch_by_task[src] = node.id

        for task in tasks:
            tid = task.get("id", "")
            deps = task.get("derived_from") or task.get("depends_on") or []
            for dep_id in deps:
                if dep_id in orch_by_task and tid in orch_by_task:
                    edges.append(
                        PipelineEdge(
                            source=orch_by_task[dep_id],
                            target=orch_by_task[tid],
                            edge_type="depends_on",
                        )
                    )

        return TransitionResult(
            nodes=nodes,
            edges=edges,
            provenance={
                "method": "workflow_engine",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source_count": len(tasks),
                "output_count": len(nodes),
                "workflow_id": workflow.id,
                "execution_mode": execution_mode or "parallel",
            },
        )
    except (ImportError, RuntimeError, Exception) as e:
        logger.debug("WorkflowEngine unavailable, using heuristic: %s", e)

    # ── Heuristic fallback: manual DAG generation ──────────────────────
    nodes = []
    edges = []

    # Map task IDs to their dependency info
    task_deps: dict[str, list[str]] = {}
    for task in tasks:
        tid = task.get("id") or f"task-{uuid.uuid4().hex[:8]}"
        deps = task.get("derived_from") or task.get("depends_on") or []
        task_deps[tid] = deps

    for task in tasks:
        task_id = task.get("id") or f"task-{uuid.uuid4().hex[:8]}"
        assignee = task.get("metadata", {}).get("assignee_type", "implementer")

        orch_id = f"orch-{uuid.uuid4().hex[:8]}"
        orch_node = PipelineNode(
            id=orch_id,
            stage="orchestration",
            label=task.get("label", ""),
            metadata={
                "agent_type": agent_map.get(assignee, "general_agent"),
                "execution_mode": execution_mode or "parallel",
                "source_task_id": task_id,
            },
            derived_from=[task_id],
        )
        nodes.append(orch_node)
        _node_store[orch_id] = asdict(orch_node)
        edges.append(PipelineEdge(source=task_id, target=orch_id, edge_type="triggers"))

    # Carry over depends_on as sequential ordering
    orch_by_task = {}
    for node in nodes:
        src = node.metadata.get("source_task_id", "")
        if src:
            orch_by_task[src] = node.id

    for task in tasks:
        tid = task.get("id", "")
        deps = task_deps.get(tid, [])
        for dep_id in deps:
            if dep_id in orch_by_task and tid in orch_by_task:
                edges.append(
                    PipelineEdge(
                        source=orch_by_task[dep_id],
                        target=orch_by_task[tid],
                        edge_type="depends_on",
                    )
                )

    return TransitionResult(
        nodes=nodes,
        edges=edges,
        provenance={
            "method": "dag_generation",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_count": len(tasks),
            "output_count": len(nodes),
            "execution_mode": execution_mode or "parallel",
        },
    )


def _get_provenance_chain(node_id: str) -> list[dict[str, Any]]:
    """Walk derived_from links back to origin, returning ordered chain."""
    chain: list[dict[str, Any]] = []
    visited: set[str] = set()
    queue = [node_id]

    while queue:
        nid = queue.pop(0)
        if nid in visited:
            continue
        visited.add(nid)
        node_data = _node_store.get(nid)
        if node_data is None:
            continue
        chain.append(node_data)
        parents = node_data.get("derived_from", [])
        queue.extend(parents)

    # Reverse so origin is first
    chain.reverse()
    return chain


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class PipelineTransitionsHandler(SecureHandler):
    """Handler for AI stage transition endpoints."""

    ROUTES = ["/api/v1/pipeline/transitions"]

    def __init__(self, ctx: dict[str, Any] | None = None):
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        cleaned = strip_version_prefix(path)
        return cleaned.startswith("/api/pipeline/transitions")

    def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Route GET requests."""
        cleaned = strip_version_prefix(path)

        client_ip = get_client_ip(handler)
        if not _transition_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded", 429)

        # GET /api/pipeline/transitions/:node_id/provenance
        parts = cleaned.split("/")
        if (
            len(parts) >= 5
            and parts[1] == "api"
            and parts[2] == "pipeline"
            and parts[3] == "transitions"
        ):
            if len(parts) == 6 and parts[5] == "provenance":
                node_id = parts[4]
                is_valid, err = validate_path_segment(
                    node_id,
                    "node_id",
                    SAFE_ID_PATTERN,
                )
                if not is_valid:
                    return error_response(cast(str, err), 400)
                return self._get_provenance(node_id)

        return None

    @handle_errors("pipeline transition")
    def handle_post(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Route POST requests to transition sub-endpoints."""
        cleaned = strip_version_prefix(path)

        client_ip = get_client_ip(handler)
        if not _transition_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded", 429)

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        if cleaned == "/api/pipeline/transitions/ideas-to-goals":
            return self._ideas_to_goals(body, query_params)
        if cleaned == "/api/pipeline/transitions/goals-to-tasks":
            return self._goals_to_tasks(body, query_params)
        if cleaned == "/api/pipeline/transitions/tasks-to-workflow":
            return self._tasks_to_workflow(body)
        if cleaned == "/api/pipeline/transitions/execute":
            return self._execute(body)

        return None

    # ── Endpoint implementations ────────────────────────────────────────

    def _ideas_to_goals(
        self,
        body: dict[str, Any],
        query_params: dict[str, Any] | None = None,
    ) -> HandlerResult:
        ideas = body.get("ideas")
        if not ideas or not isinstance(ideas, list):
            return error_response("'ideas' must be a non-empty list", 400)

        try:
            mode = _extract_mode(query_params or {})
        except ValueError as exc:
            return error_response(str(exc), 400)

        context = body.get("context")
        result = _ideas_to_goals_logic(ideas, context, mode=mode)
        return json_response(self._serialize_result(result))

    def _goals_to_tasks(
        self,
        body: dict[str, Any],
        query_params: dict[str, Any] | None = None,
    ) -> HandlerResult:
        goals = body.get("goals")
        if not goals or not isinstance(goals, list):
            return error_response("'goals' must be a non-empty list", 400)

        try:
            mode = _extract_mode(query_params or {})
        except ValueError as exc:
            return error_response(str(exc), 400)

        constraints = body.get("constraints") or {}
        max_tasks = constraints.get("max_tasks")
        result = _goals_to_tasks_logic(goals, max_tasks, mode=mode)
        return json_response(self._serialize_result(result))

    def _tasks_to_workflow(self, body: dict[str, Any]) -> HandlerResult:
        tasks = body.get("tasks")
        if not tasks or not isinstance(tasks, list):
            return error_response("'tasks' must be a non-empty list", 400)

        execution_mode = body.get("execution_mode")
        result = _tasks_to_workflow_logic(tasks, execution_mode)
        return json_response(self._serialize_result(result))

    def _execute(self, body: dict[str, Any]) -> HandlerResult:
        workflow_nodes = body.get("nodes")
        workflow_edges = body.get("edges")
        dry_run = body.get("dry_run", False)

        if not workflow_nodes or not isinstance(workflow_nodes, list):
            return error_response("'nodes' must be a non-empty list", 400)

        execution_id = f"exec-{uuid.uuid4().hex[:12]}"

        if dry_run:
            return json_response(
                {
                    "execution_id": execution_id,
                    "status": "dry_run",
                    "plan": {
                        "node_count": len(workflow_nodes),
                        "edge_count": len(workflow_edges) if workflow_edges else 0,
                        "estimated_steps": len(workflow_nodes),
                    },
                }
            )

        # Real execution: store and mark as started
        return json_response(
            {
                "execution_id": execution_id,
                "status": "started",
                "node_count": len(workflow_nodes),
            }
        )

    def _get_provenance(self, node_id: str) -> HandlerResult:
        chain = _get_provenance_chain(node_id)
        if not chain:
            return error_response(f"Node '{node_id}' not found", 404)

        return json_response(
            {
                "node_id": node_id,
                "chain": chain,
                "depth": len(chain),
            }
        )

    # ── Serialisation helpers ───────────────────────────────────────────

    @staticmethod
    def _serialize_result(result: TransitionResult) -> dict[str, Any]:
        return {
            "nodes": [asdict(n) for n in result.nodes],
            "edges": [asdict(e) for e in result.edges],
            "provenance": result.provenance,
        }
