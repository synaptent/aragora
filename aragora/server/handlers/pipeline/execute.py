"""Pipeline execution trigger handler.

Executes a pipeline's Stage 4 (Orchestration) nodes via the self-improvement
pipeline, bridging the visual canvas editor to autonomous code execution.

Endpoints:
- POST /api/v1/pipeline/:pipeline_id/execute  Start execution
- GET  /api/v1/pipeline/:pipeline_id/execute   Get execution status
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from aragora.server.versioning.compat import strip_version_prefix

from ..base import (
    SAFE_ID_PATTERN,
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
    validate_path_segment,
    handle_errors,
)
from ..utils.decorators import require_permission
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

_execute_limiter = RateLimiter(requests_per_minute=10)

# Active pipeline executions: pipeline_id -> execution state
_executions: dict[str, dict[str, Any]] = {}
_execution_tasks: dict[str, asyncio.Task[Any]] = {}


class PipelineExecuteHandler(BaseHandler):
    """Handler for pipeline execution via self-improvement pipeline.

    Converts orchestration nodes from a pipeline's Stage 4 into
    PrioritizedGoals and executes them through SelfImprovePipeline.
    """

    ROUTES = ["/api/v1/pipeline"]

    def __init__(self, ctx: dict[str, Any] | None = None):
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        cleaned = strip_version_prefix(path)
        # Match /api/pipeline/:id/execute
        parts = cleaned.strip("/").split("/")
        return (
            len(parts) >= 4
            and parts[0] == "api"
            and parts[1] == "pipeline"
            and parts[3] == "execute"
        )

    def _extract_pipeline_id(self, path: str) -> str | None:
        """Extract pipeline_id from /api/pipeline/:id/execute."""
        cleaned = strip_version_prefix(path)
        parts = cleaned.strip("/").split("/")
        if len(parts) >= 4 and parts[1] == "pipeline" and parts[3] == "execute":
            pid = parts[2]
            if validate_path_segment(pid, "pipeline_id", SAFE_ID_PATTERN)[0]:
                return pid
        return None

    @require_permission("pipeline:read")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """GET /api/v1/pipeline/:pipeline_id/execute — execution status."""
        pipeline_id = self._extract_pipeline_id(path)
        if not pipeline_id:
            return error_response("Invalid pipeline ID", 400)

        execution = _executions.get(pipeline_id)
        if not execution:
            return json_response({"pipeline_id": pipeline_id, "status": "not_started"})

        return json_response(execution)

    @handle_errors("pipeline execute")
    @require_permission("pipeline:execute")
    async def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """POST /api/v1/pipeline/:pipeline_id/execute — start execution."""
        client_ip = get_client_ip(handler)
        if not _execute_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded", 429)

        pipeline_id = self._extract_pipeline_id(path)
        if not pipeline_id:
            return error_response("Invalid pipeline ID", 400)

        # Check if already executing
        if pipeline_id in _execution_tasks:
            task = _execution_tasks[pipeline_id]
            if not task.done():
                return error_response("Pipeline is already executing", 409)

        body = self.read_json_body(handler) or {}
        budget_limit = body.get("budget_limit_usd")
        require_approval = body.get("require_approval", False)
        dry_run = body.get("dry_run", False)
        use_hardened = body.get("use_hardened_orchestrator", False)

        # Load orchestration nodes from the pipeline graph
        orch_nodes = self._load_orchestration_nodes(pipeline_id)
        if not orch_nodes:
            return error_response("No orchestration nodes found in pipeline", 404)

        # Convert to goals
        goals = self._convert_to_goals(orch_nodes, pipeline_id)

        cycle_id = f"pipe-{uuid.uuid4().hex[:12]}"

        # Store execution state
        _executions[pipeline_id] = {
            "pipeline_id": pipeline_id,
            "cycle_id": cycle_id,
            "status": "started",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "goal_count": len(goals),
            "dry_run": dry_run,
        }

        if dry_run:
            _executions[pipeline_id]["status"] = "preview"
            _executions[pipeline_id]["goals"] = [
                {"description": g.description, "track": g.track.value, "priority": g.priority}
                for g in goals
            ]
            _executions[pipeline_id]["runtime"] = "decision_plan"
            return json_response(_executions[pipeline_id])

        if use_hardened:
            logger.debug(
                "Pipeline execute requested hardened orchestrator for %s; routing through canonical DecisionPlan runtime instead",
                pipeline_id,
            )

        from aragora.pipeline.canonical_execution import (
            build_decision_plan_from_orchestration,
            queue_plan_execution,
        )

        synthetic_nodes = [
            {
                "id": f"goal-{index}",
                "label": goal.description,
                "data": {
                    "orch_type": "human_gate" if require_approval else "agent_task",
                    "track": getattr(goal.track, "value", str(getattr(goal, "track", "core"))),
                },
            }
            for index, goal in enumerate(goals, start=1)
        ]
        plan, tasks = build_decision_plan_from_orchestration(
            subject_id=pipeline_id,
            subject_label=f"Pipeline {pipeline_id}",
            nodes=synthetic_nodes,
            edges=[],
            source_surface="pipeline_execute",
            metadata={"pipeline_id": pipeline_id},
            budget_limit_usd=budget_limit,
            execution_mode="workflow",
            require_task_approval=require_approval,
        )
        launch = queue_plan_execution(plan, execution_mode="workflow")
        _executions[pipeline_id].update(
            {
                "status": "started",
                "runtime": "decision_plan",
                "plan_id": plan.id,
                "execution_id": launch["execution_id"],
                "correlation_id": launch["correlation_id"],
                "record_status": launch["status"],
                "tasks_total": len(tasks),
            }
        )

        # Start background execution
        task = asyncio.create_task(
            self._execute_pipeline(
                pipeline_id, cycle_id, goals, budget_limit, require_approval, use_hardened
            )
        )
        _execution_tasks[pipeline_id] = task

        return json_response(
            {
                "pipeline_id": pipeline_id,
                "cycle_id": cycle_id,
                "status": "started",
                "runtime": "decision_plan",
                "plan_id": plan.id,
                "execution_id": launch["execution_id"],
                "correlation_id": launch["correlation_id"],
            },
            status=202,
        )

    def _load_orchestration_nodes(self, pipeline_id: str) -> list[dict[str, Any]]:
        """Load Stage 4 orchestration nodes from the pipeline graph."""
        try:
            from aragora.pipeline.graph_store import get_graph_store

            store = get_graph_store()
            graph = store.get(pipeline_id)
            if not graph:
                return []

            # Filter to orchestration stage nodes
            nodes = []
            graph_nodes = getattr(graph, "nodes", {})
            if isinstance(graph_nodes, dict):
                for node_id, node in graph_nodes.items():
                    node_data = getattr(node, "data", node) if not isinstance(node, dict) else node
                    stage = node_data.get("stage", "")
                    if stage == "orchestration":
                        nodes.append({"id": node_id, **node_data})
            return nodes
        except (ImportError, RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Failed to load orchestration nodes: %s", type(e).__name__)
            return []

    def _convert_to_goals(self, orch_nodes: list[dict[str, Any]], pipeline_id: str) -> list[Any]:
        """Convert orchestration nodes to PrioritizedGoal objects."""
        from aragora.nomic.meta_planner import PrioritizedGoal, Track

        goals = []
        for i, node in enumerate(orch_nodes, start=1):
            label = node.get("label", node.get("description", f"Task {i}"))
            orch_type = node.get("orch_type", node.get("orchType", "agent_task"))
            _assigned_agent = node.get("assigned_agent", node.get("assignedAgent", ""))

            # Map orch type to track
            track_map = {
                "agent_task": Track.CORE,
                "debate": Track.CORE,
                "human_gate": Track.CORE,
                "verification": Track.QA,
                "parallel_fan": Track.DEVELOPER,
                "merge": Track.DEVELOPER,
            }
            track = track_map.get(orch_type, Track.CORE)

            goals.append(
                PrioritizedGoal(
                    id=f"pipe-goal-{pipeline_id[:8]}-{i}",
                    track=track,
                    description=label,
                    rationale=f"From pipeline {pipeline_id} orchestration node {node.get('id', i)}",
                    estimated_impact="medium",
                    priority=i,
                    focus_areas=[orch_type],
                    file_hints=[],
                )
            )

        return goals

    async def _execute_pipeline(
        self,
        pipeline_id: str,
        cycle_id: str,
        goals: list[Any],
        budget_limit: float | None,
        require_approval: bool,
        use_hardened: bool = False,
    ) -> None:
        """Execute pipeline goals via the canonical DecisionPlan runtime."""
        # Wire WebSocket emitter for real-time progress
        emitter = _get_emitter()
        execution_state = _executions.get(pipeline_id, {})
        try:
            from aragora.pipeline.canonical_execution import (
                build_decision_plan_from_orchestration,
                execute_queued_plan,
                queue_plan_execution,
            )
            from aragora.pipeline.plan_store import get_plan_store

            plan = None
            plan_id = execution_state.get("plan_id")
            execution_id = execution_state.get("execution_id")
            correlation_id = execution_state.get("correlation_id")
            if not plan_id or not execution_id or not correlation_id:
                synthetic_nodes = [
                    {
                        "id": f"goal-{index}",
                        "label": getattr(goal, "description", f"Goal {index}"),
                        "data": {
                            "orch_type": "human_gate" if require_approval else "agent_task",
                        },
                    }
                    for index, goal in enumerate(goals, start=1)
                ]
                plan, _tasks = build_decision_plan_from_orchestration(
                    subject_id=pipeline_id,
                    subject_label=f"Pipeline {pipeline_id}",
                    nodes=synthetic_nodes,
                    edges=[],
                    source_surface="pipeline_execute",
                    metadata={"pipeline_id": pipeline_id},
                    budget_limit_usd=budget_limit,
                    execution_mode="workflow",
                    require_task_approval=require_approval,
                )
                launch = queue_plan_execution(plan, execution_mode="workflow")
                execution_state.update(
                    {
                        "runtime": "decision_plan",
                        "plan_id": plan.id,
                        "execution_id": launch["execution_id"],
                        "correlation_id": launch["correlation_id"],
                        "record_status": launch["status"],
                    }
                )
                plan_id = launch["plan_id"]
                execution_id = launch["execution_id"]
                correlation_id = launch["correlation_id"]

            store = get_plan_store()
            plan = store.get(str(plan_id)) or plan
            if plan is None:
                raise ValueError(f"Plan not found: {plan_id}")

            if emitter:
                await emitter.emit_started(
                    pipeline_id,
                    {
                        "cycle_id": cycle_id,
                        "plan_id": plan_id,
                        "execution_id": execution_id,
                        "goal_count": len(goals),
                    },
                )

            _executions[pipeline_id]["status"] = "running"
            outcome, record, decision_receipt = await execute_queued_plan(
                plan,
                execution_id=str(execution_id),
                correlation_id=str(correlation_id),
                execution_mode="workflow",
            )
            receipt_bundle: dict[str, Any] = decision_receipt or {}
            try:
                from aragora.pipeline.receipt_generator import generate_pipeline_receipt

                receipt_bundle = {
                    **receipt_bundle,
                    "pipeline_receipt": await generate_pipeline_receipt(
                        pipeline_id,
                        {
                            **(record or {}),
                            "execution_id": execution_id,
                            "correlation_id": correlation_id,
                            "status": "completed" if outcome.success else "failed",
                        },
                    ),
                }
            except (ImportError, RuntimeError, ValueError, TypeError, OSError) as exc:
                logger.debug("Pipeline provenance receipt generation skipped: %s", exc)
            _executions[pipeline_id].update(
                {
                    "status": "completed" if outcome.success else "failed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "total_subtasks": outcome.tasks_total,
                    "completed_subtasks": outcome.tasks_completed,
                    "failed_subtasks": max(0, outcome.tasks_total - outcome.tasks_completed),
                    "record": record,
                    "outcome": outcome.to_dict(),
                    "receipt": receipt_bundle or decision_receipt,
                }
            )

            if emitter:
                if outcome.success:
                    await emitter.emit_completed(pipeline_id, _executions[pipeline_id])
                else:
                    await emitter.emit_failed(
                        pipeline_id,
                        outcome.error or "Pipeline execution failed",
                    )

        except asyncio.CancelledError:
            _executions[pipeline_id].update(
                {
                    "status": "cancelled",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            if emitter:
                await emitter.emit_failed(pipeline_id, "Pipeline cancelled")
        except Exception as e:  # noqa: BLE001 - background execution must preserve error state
            logger.error("Pipeline execution failed: %s", e)
            _executions[pipeline_id].update(
                {
                    "status": "failed",
                    "error": str(e),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            if emitter:
                await emitter.emit_failed(pipeline_id, str(e))
        finally:
            _execution_tasks.pop(pipeline_id, None)

    async def _execute_via_hardened(
        self,
        pipeline_id: str,
        cycle_id: str,
        goals: list[Any],
        budget_limit: float | None,
        require_approval: bool,
        emitter: Any | None,
    ) -> None:
        """Execute pipeline goals via HardenedOrchestrator with full safety gates."""
        try:
            from aragora.nomic.hardened_orchestrator import HardenedOrchestrator

            if emitter:
                await emitter.emit_started(
                    pipeline_id,
                    {"cycle_id": cycle_id, "goal_count": len(goals), "backend": "hardened"},
                )

            orchestrator = HardenedOrchestrator(
                use_worktree_isolation=True,
                enable_gauntlet_validation=True,
                generate_receipts=True,
                budget_limit_usd=budget_limit,
                require_approval=require_approval,
            )

            completed = 0
            failed = 0
            for goal in goals:
                try:
                    result = await orchestrator.execute_goal(goal.description)
                    if getattr(result, "success", False):
                        completed += 1
                    else:
                        failed += 1
                except (RuntimeError, ValueError, OSError, TypeError) as exc:
                    logger.warning("Hardened goal execution failed: %s", exc)
                    failed += 1

            status = "completed" if completed > 0 else "failed"
            _executions[pipeline_id].update(
                {
                    "status": status,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "total_subtasks": len(goals),
                    "completed_subtasks": completed,
                    "failed_subtasks": failed,
                    "backend": "hardened_orchestrator",
                }
            )

            # Create convoy for hardened execution (best-effort)
            try:
                from aragora.workspace.convoy import ConvoyTracker

                convoy_id = f"convoy-{uuid.uuid4().hex[:12]}"
                tracker = ConvoyTracker()
                goal_desc = "; ".join(g.description for g in goals[:5])
                convoy = await tracker.create_convoy(
                    workspace_id=pipeline_id,
                    rig_id=pipeline_id,
                    name=f"Hardened pipeline: {goal_desc[:80]}",
                    bead_ids=[f"pipeline:{pipeline_id}", f"cycle:{cycle_id}"],
                    convoy_id=convoy_id,
                    metadata={
                        "pipeline_id": pipeline_id,
                        "cycle_id": cycle_id,
                        "status": status,
                        "backend": "hardened_orchestrator",
                    },
                )
                _executions[pipeline_id]["convoy_id"] = convoy.convoy_id
            except (ImportError, RuntimeError, ValueError, OSError, TypeError, AttributeError) as e:
                logger.debug("Convoy creation skipped: %s", type(e).__name__)

            if emitter:
                if status == "completed":
                    await emitter.emit_completed(pipeline_id, _executions[pipeline_id])
                else:
                    await emitter.emit_failed(pipeline_id, "No goals completed")

        except ImportError:
            logger.debug("HardenedOrchestrator not available, falling back to basic pipeline")
            _executions[pipeline_id].update(
                {
                    "status": "failed",
                    "error": "HardenedOrchestrator not available",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            if emitter:
                await emitter.emit_failed(pipeline_id, "HardenedOrchestrator not available")
        except (RuntimeError, ValueError, TypeError, OSError) as e:
            logger.error("Hardened pipeline execution failed: %s", type(e).__name__)
            _executions[pipeline_id].update(
                {
                    "status": "failed",
                    "error": "Hardened pipeline execution failed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            if emitter:
                await emitter.emit_failed(pipeline_id, "Hardened pipeline execution failed")
        finally:
            _execution_tasks.pop(pipeline_id, None)


def _get_emitter() -> Any:
    """Get the pipeline stream emitter, or None if unavailable."""
    try:
        from aragora.server.stream.pipeline_stream import get_pipeline_emitter

        return get_pipeline_emitter()
    except (ImportError, RuntimeError):
        return None
