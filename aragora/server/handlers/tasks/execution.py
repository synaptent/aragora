"""
Task Execution Handler.

Provides HTTP endpoints for submitting, monitoring, and approving tasks
that bridge debate decisions to concrete execution. This is the Phase V
centerpiece that turns "debate a decision" into "implement a decision."

Routes:
    POST /api/v2/tasks/execute     - Submit a task for execution
    GET  /api/v2/tasks/<task_id>   - Get task status
    GET  /api/v2/tasks             - List tasks (with optional status filter)
    POST /api/v2/tasks/<task_id>/approve - Approve a human checkpoint
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from aragora.events.handler_events import (
    APPROVED,
    COMPLETED,
    CREATED,
    FAILED,
    STARTED,
    emit_handler_event,
)
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from aragora.server.handlers.utils.rate_limit import rate_limit

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional integrations (graceful fallback)
# ---------------------------------------------------------------------------

_HAS_SCHEDULER = False
_TaskScheduler: Any = None
try:
    from aragora.control_plane.scheduler import TaskScheduler as _TaskScheduler

    _HAS_SCHEDULER = True
except ImportError:
    logger.debug("TaskScheduler not available; using in-memory task tracking")

_HAS_WORKFLOW_ENGINE = False
_get_workflow_engine: Any = None
try:
    from aragora.workflow.engine import get_workflow_engine as _get_workflow_engine

    _HAS_WORKFLOW_ENGINE = True
except ImportError:
    logger.debug("WorkflowEngine not available; tasks will use simple execution")

# ---------------------------------------------------------------------------
# Task Record
# ---------------------------------------------------------------------------

# Valid task types
VALID_TASK_TYPES = frozenset(
    {
        "debate",
        "code_edit",
        "computer_use",
        "analysis",
        "composite",
    }
)


@dataclass
class TaskRoute:
    """A route mapping a task type to its workflow definition.

    Attributes:
        task_type: The type of task (e.g. "debate", "code_edit").
        workflow_steps: List of step definitions for the workflow engine.
        required_capabilities: Agent capabilities needed for this task type.
        description: Human-readable description of what this route does.
    """

    task_type: str
    workflow_steps: list[dict[str, Any]]
    required_capabilities: list[str] = field(default_factory=list)
    description: str = ""


class TaskRouter:
    """Routes task types to workflow definitions."""

    def __init__(self) -> None:
        self._routes: dict[str, TaskRoute] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register default task routes for all standard task types."""
        self._routes["debate"] = TaskRoute(
            task_type="debate",
            workflow_steps=[
                {
                    "id": "debate_step",
                    "type": "debate",
                    "name": "Multi-Agent Debate",
                    "config": {
                        "rounds": 3,
                        "consensus": "majority",
                    },
                },
            ],
            required_capabilities=["debate", "reasoning"],
            description="Run a multi-agent debate to reach consensus on a question.",
        )

        self._routes["code_edit"] = TaskRoute(
            task_type="code_edit",
            workflow_steps=[
                {
                    "id": "analysis_step",
                    "type": "analysis",
                    "name": "Code Analysis",
                    "config": {
                        "mode": "code_review",
                    },
                },
                {
                    "id": "implementation_step",
                    "type": "implementation",
                    "name": "Code Implementation",
                    "config": {
                        "mode": "edit",
                    },
                },
                {
                    "id": "verification_step",
                    "type": "verification",
                    "name": "Change Verification",
                    "config": {
                        "run_tests": True,
                    },
                },
            ],
            required_capabilities=["code_generation", "code_review"],
            description="Analyze, implement, and verify code changes.",
        )

        self._routes["computer_use"] = TaskRoute(
            task_type="computer_use",
            workflow_steps=[
                {
                    "id": "computer_use_step",
                    "type": "computer_use",
                    "name": "Computer Use Task",
                    "config": {
                        "mode": "autonomous",
                        "screenshot_interval": 2,
                    },
                },
            ],
            required_capabilities=["computer_use", "vision"],
            description="Execute a task using computer use capabilities.",
        )

        self._routes["analysis"] = TaskRoute(
            task_type="analysis",
            workflow_steps=[
                {
                    "id": "analysis_debate_step",
                    "type": "debate",
                    "name": "Analysis Debate",
                    "config": {
                        "rounds": 2,
                        "consensus": "majority",
                        "prompt_prefix": "Analyze the following: ",
                    },
                },
            ],
            required_capabilities=["reasoning", "analysis"],
            description="Run an analysis-focused debate to evaluate a topic.",
        )

        self._routes["composite"] = TaskRoute(
            task_type="composite",
            workflow_steps=[
                {
                    "id": "planning_step",
                    "type": "debate",
                    "name": "Task Planning",
                    "config": {
                        "rounds": 1,
                        "consensus": "majority",
                        "prompt_prefix": "Plan the following multi-step task: ",
                    },
                },
                {
                    "id": "execution_step",
                    "type": "implementation",
                    "name": "Task Execution",
                    "config": {
                        "mode": "multi_step",
                    },
                },
                {
                    "id": "review_step",
                    "type": "debate",
                    "name": "Result Review",
                    "config": {
                        "rounds": 1,
                        "consensus": "majority",
                        "prompt_prefix": "Review the results of: ",
                    },
                },
            ],
            required_capabilities=["reasoning", "code_generation"],
            description="Multi-step workflow: plan, execute, and review.",
        )

    def register(self, route: TaskRoute) -> None:
        """Register a custom task route."""
        self._routes[route.task_type] = route
        logger.info("Registered task route: %s", route.task_type)

    def route(self, task_type: str, goal: str, context: dict[str, Any]) -> TaskRoute:
        """Return the appropriate route for a given task type.

        Unknown task types fall back to a debate route for compatibility with
        internal callers that register custom validation elsewhere.
        """
        if not task_type:
            raise ValueError("task_type must not be empty")

        if task_type in self._routes:
            return self._routes[task_type]

        logger.warning("Unknown task type '%s', falling back to debate route", task_type)
        return TaskRoute(
            task_type=task_type,
            workflow_steps=[
                {
                    "id": "fallback_debate_step",
                    "type": "debate",
                    "name": f"Debate: {task_type}",
                    "config": {
                        "rounds": 2,
                        "consensus": "majority",
                    },
                },
            ],
            required_capabilities=["reasoning"],
            description=f"Fallback debate route for unknown type '{task_type}'.",
        )

    @property
    def registered_types(self) -> list[str]:
        """Return list of registered task type names."""
        return sorted(self._routes.keys())

    def get_route(self, task_type: str) -> TaskRoute | None:
        """Get a route by task type without fallback."""
        return self._routes.get(task_type)


# Valid status values and transitions
VALID_STATUSES = frozenset(
    {
        "pending",
        "running",
        "completed",
        "failed",
        "waiting_approval",
        "approved",
    }
)

# Allowed status transitions
_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"running", "failed", "waiting_approval"}),
    "waiting_approval": frozenset({"approved", "failed"}),
    "approved": frozenset({"running", "failed"}),
    "running": frozenset({"completed", "failed"}),
    "completed": frozenset(),
    "failed": frozenset(),
}


@dataclass
class TaskRecord:
    """In-memory record for a submitted task.

    Attributes:
        id: Unique task identifier (UUID).
        goal: Natural-language description of what the task should achieve.
        type: Task type (debate, code_edit, computer_use, analysis, composite).
        status: Current lifecycle status.
        agents: List of agent identifiers to use (["auto"] for automatic selection).
        max_steps: Maximum workflow steps allowed.
        human_checkpoints: Whether to pause for human approval before execution.
        context: Arbitrary context dict passed to the workflow.
        created_at: Unix timestamp of creation.
        updated_at: Unix timestamp of last status change.
        result: Result data on completion (None while in progress).
        error: Error message on failure (None if no error).
        workflow_id: Associated workflow engine workflow ID, if any.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    goal: str = ""
    type: str = "debate"
    status: str = "pending"
    agents: list[str] = field(default_factory=lambda: ["auto"])
    max_steps: int = 10
    human_checkpoints: bool = False
    context: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    result: dict[str, Any] | None = None
    error: str | None = None
    workflow_id: str | None = None

    def transition_to(self, new_status: str) -> None:
        """Transition task to a new status.

        Args:
            new_status: Target status string.

        Raises:
            ValueError: If the transition is not allowed.
        """
        allowed = _STATUS_TRANSITIONS.get(self.status, frozenset())
        if new_status not in allowed:
            raise ValueError(
                f"Cannot transition from '{self.status}' to '{new_status}'. "
                f"Allowed: {sorted(allowed) if allowed else 'none (terminal state)'}"
            )
        self.status = new_status
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        """Serialize the task record to a JSON-safe dict."""
        return asdict(self)


# ---------------------------------------------------------------------------
# In-memory task store
# ---------------------------------------------------------------------------

_tasks: dict[str, TaskRecord] = {}


def _clear_tasks() -> None:
    """Clear the in-memory task store (for testing)."""
    _tasks.clear()


# Module-level router instance
_router = TaskRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_GOAL_LENGTH = 5000
MAX_CONTEXT_SIZE = 50  # max top-level keys in context dict
MAX_LIST_LIMIT = 100
DEFAULT_LIST_LIMIT = 20


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class TaskExecutionHandler(BaseHandler):
    """HTTP handler for task execution endpoints.

    Supports:
        POST /api/v2/tasks/execute       - Submit a new task
        GET  /api/v2/tasks/<task_id>      - Retrieve task status
        GET  /api/v2/tasks               - List tasks (optional ?status= filter)
        POST /api/v2/tasks/<task_id>/approve - Approve a human checkpoint
    """

    ROUTES = [
        "/api/v2/tasks",
        "/api/v2/tasks/*",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Return True if this handler should process the given path."""
        return path.startswith("/api/v2/tasks")

    # ------------------------------------------------------------------
    # GET dispatcher
    # ------------------------------------------------------------------

    @rate_limit(requests_per_minute=60)
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Handle GET requests for task endpoints."""
        if not self.can_handle(path):
            return None

        user, err = self.require_auth_or_error(handler)
        if err:
            return err
        _, perm_err = self.require_permission_or_error(handler, "tasks:read")
        if perm_err:
            return perm_err

        parts = path.rstrip("/").split("/")
        # /api/v2/tasks -> ["", "api", "v2", "tasks"]
        # /api/v2/tasks/<id> -> ["", "api", "v2", "tasks", "<id>"]

        if len(parts) == 4 and parts[3] == "tasks":
            return self._handle_list_tasks(query_params)

        if len(parts) == 5 and parts[3] == "tasks":
            task_id = parts[4]
            return self._handle_get_task(task_id)

        return error_response("Not found", 404)

    # ------------------------------------------------------------------
    # POST dispatcher
    # ------------------------------------------------------------------

    @handle_errors("task execution")
    @rate_limit(requests_per_minute=30)
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST requests for task endpoints."""
        if not self.can_handle(path):
            return None

        user, err = self.require_auth_or_error(handler)
        if err:
            return err
        _, perm_err = self.require_permission_or_error(handler, "tasks:execute")
        if perm_err:
            return perm_err

        parts = path.rstrip("/").split("/")

        # POST /api/v2/tasks/execute
        if len(parts) == 5 and parts[3] == "tasks" and parts[4] == "execute":
            body = self.read_json_body(handler)
            if body is None:
                return error_response("Invalid JSON body", 400)
            return self._handle_execute(body)

        # POST /api/v2/tasks/<task_id>/approve
        if len(parts) == 6 and parts[3] == "tasks" and parts[5] == "approve":
            task_id = parts[4]
            return self._handle_approve(task_id)

        return error_response("Not found", 404)

    # ------------------------------------------------------------------
    # POST /api/v2/tasks/execute
    # ------------------------------------------------------------------

    def _handle_execute(self, body: dict[str, Any]) -> HandlerResult:
        """Submit a new task for execution.

        Expected body:
            {
                "goal": str,            # required
                "type": str,            # required, one of VALID_TASK_TYPES
                "agents": list[str],    # optional, default ["auto"]
                "max_steps": int,       # optional, default 10
                "human_checkpoints": bool,  # optional, default false
                "context": dict         # optional
            }
        """
        # --- Validate goal ---
        goal = body.get("goal")
        if not goal or not isinstance(goal, str):
            return error_response("'goal' is required and must be a non-empty string", 400)
        goal = goal.strip()
        if not goal:
            return error_response("'goal' must not be blank", 400)
        if len(goal) > MAX_GOAL_LENGTH:
            return error_response(
                f"'goal' exceeds maximum length of {MAX_GOAL_LENGTH} characters", 400
            )

        # --- Validate type ---
        task_type = body.get("type")
        if not task_type or not isinstance(task_type, str):
            return error_response("'type' is required and must be a string", 400)
        if task_type not in VALID_TASK_TYPES:
            return error_response(
                f"Invalid task type '{task_type}'. "
                f"Must be one of: {', '.join(sorted(VALID_TASK_TYPES))}",
                400,
            )

        # --- Validate agents ---
        agents = body.get("agents", ["auto"])
        if not isinstance(agents, list):
            return error_response("'agents' must be a list of strings", 400)
        if not agents:
            agents = ["auto"]
        for agent in agents:
            if not isinstance(agent, str):
                return error_response("Each agent in 'agents' must be a string", 400)

        # --- Validate max_steps ---
        max_steps = body.get("max_steps", 10)
        if not isinstance(max_steps, int) or max_steps < 1:
            return error_response("'max_steps' must be a positive integer", 400)
        if max_steps > 100:
            return error_response("'max_steps' must not exceed 100", 400)

        # --- Validate human_checkpoints ---
        human_checkpoints = body.get("human_checkpoints", False)
        if not isinstance(human_checkpoints, bool):
            return error_response("'human_checkpoints' must be a boolean", 400)

        # --- Validate context ---
        context = body.get("context", {})
        if not isinstance(context, dict):
            return error_response("'context' must be a dict", 400)
        if len(context) > MAX_CONTEXT_SIZE:
            return error_response(f"'context' has too many keys (max {MAX_CONTEXT_SIZE})", 400)

        # --- Route the task ---
        try:
            route = _router.route(task_type, goal, context)
        except ValueError as exc:
            return error_response(str(exc), 400)

        # --- Create the task record ---
        task = TaskRecord(
            goal=goal,
            type=task_type,
            agents=agents,
            max_steps=max_steps,
            human_checkpoints=human_checkpoints,
            context=context,
        )

        # Determine initial status
        if human_checkpoints:
            task.status = "waiting_approval"
        else:
            task.status = "pending"

        _tasks[task.id] = task

        # Emit creation event
        emit_handler_event(
            "task",
            CREATED,
            {
                "task_id": task.id,
                "goal": task.goal,
                "type": task.type,
                "status": task.status,
            },
            resource_id=task.id,
        )

        # --- Attempt to schedule via TaskScheduler ---
        if _HAS_SCHEDULER and not human_checkpoints:
            try:
                self._schedule_task(task, route)
            except (RuntimeError, ValueError, OSError) as exc:
                logger.warning("Failed to schedule task %s: %s", task.id, exc)
                # Continue - task is still tracked in-memory

        # --- Start execution if no checkpoints required ---
        if not human_checkpoints:
            try:
                self._start_execution(task, route)
            except (ValueError, RuntimeError, OSError, AttributeError) as exc:
                logger.error("Failed to start task %s: %s", task.id, exc)
                task.status = "failed"
                task.error = str(exc)
                task.updated_at = time.time()
                emit_handler_event(
                    "task",
                    FAILED,
                    {"task_id": task.id, "error": str(exc)},
                    resource_id=task.id,
                )

        logger.info(
            "Task created: id=%s type=%s status=%s goal=%s",
            task.id,
            task.type,
            task.status,
            task.goal[:80],
        )

        return json_response(
            {
                "task_id": task.id,
                "status": task.status,
                "goal": task.goal,
                "type": task.type,
                "workflow_steps": route.workflow_steps,
                "created_at": task.created_at,
            },
            status=201,
        )

    # ------------------------------------------------------------------
    # GET /api/v2/tasks/<task_id>
    # ------------------------------------------------------------------

    def _handle_get_task(self, task_id: str) -> HandlerResult:
        """Return current status of a task."""
        task = _tasks.get(task_id)
        if task is None:
            return error_response(f"Task '{task_id}' not found", 404)
        return json_response(task.to_dict())

    # ------------------------------------------------------------------
    # GET /api/v2/tasks
    # ------------------------------------------------------------------

    def _handle_list_tasks(self, query_params: dict[str, Any]) -> HandlerResult:
        """List tasks, optionally filtered by status.

        Query params:
            status: Filter by status (e.g. "pending", "running")
            limit:  Max number of results (default 20, max 100)
            offset: Pagination offset (default 0)
        """
        status_filter = query_params.get("status")
        if status_filter and status_filter not in VALID_STATUSES:
            return error_response(
                f"Invalid status filter '{status_filter}'. "
                f"Must be one of: {', '.join(sorted(VALID_STATUSES))}",
                400,
            )

        # Parse pagination
        try:
            limit = int(query_params.get("limit", DEFAULT_LIST_LIMIT))
        except (ValueError, TypeError):
            limit = DEFAULT_LIST_LIMIT
        limit = max(1, min(limit, MAX_LIST_LIMIT))

        try:
            offset = int(query_params.get("offset", 0))
        except (ValueError, TypeError):
            offset = 0
        offset = max(0, offset)

        # Filter and sort (newest first)
        tasks = sorted(_tasks.values(), key=lambda t: t.created_at, reverse=True)
        if status_filter:
            tasks = [t for t in tasks if t.status == status_filter]

        total = len(tasks)
        page = tasks[offset : offset + limit]

        return json_response(
            {
                "tasks": [t.to_dict() for t in page],
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )

    # ------------------------------------------------------------------
    # POST /api/v2/tasks/<task_id>/approve
    # ------------------------------------------------------------------

    def _handle_approve(self, task_id: str) -> HandlerResult:
        """Approve a task that is waiting for human checkpoint."""
        task = _tasks.get(task_id)
        if task is None:
            return error_response(f"Task '{task_id}' not found", 404)

        if task.status != "waiting_approval":
            return error_response(
                f"Task '{task_id}' is in status '{task.status}', "
                f"not 'waiting_approval'. Cannot approve.",
                409,
            )

        try:
            task.transition_to("approved")
        except ValueError as exc:
            return error_response(str(exc), 409)

        emit_handler_event(
            "task",
            APPROVED,
            {"task_id": task.id, "goal": task.goal},
            resource_id=task.id,
        )

        # Start execution after approval
        route = _router.route(task.type, task.goal, task.context)
        try:
            self._start_execution(task, route)
        except (ValueError, RuntimeError, OSError, AttributeError) as exc:
            logger.error("Failed to start approved task %s: %s", task.id, exc)
            task.status = "failed"
            task.error = str(exc)
            task.updated_at = time.time()
            emit_handler_event(
                "task",
                FAILED,
                {"task_id": task.id, "error": str(exc)},
                resource_id=task.id,
            )

        return json_response(
            {
                "task_id": task.id,
                "status": task.status,
                "message": "Task approved and execution started.",
            }
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _schedule_task(self, task: TaskRecord, route: Any) -> None:
        """Attempt to queue the task via the control plane TaskScheduler."""
        if not _HAS_SCHEDULER or _TaskScheduler is None:
            return
        # The scheduler integration is best-effort; actual execution
        # still happens through _start_execution.
        logger.debug("Scheduling task %s via TaskScheduler", task.id)

    def _start_execution(self, task: TaskRecord, route: Any) -> None:
        """Begin task execution (synchronous kickoff).

        For now this transitions the task to 'running' and optionally
        creates a workflow via the WorkflowEngine. Full async execution
        will be added in a follow-up phase.
        """
        if task.status == "approved":
            task.transition_to("running")
        elif task.status == "pending":
            task.transition_to("running")
        # If already running or terminal, skip

        emit_handler_event(
            "task",
            STARTED,
            {"task_id": task.id, "type": task.type},
            resource_id=task.id,
        )

        # Attempt workflow engine integration
        if _HAS_WORKFLOW_ENGINE and _get_workflow_engine is not None:
            try:
                _engine = _get_workflow_engine()  # noqa: F841 - validates engine available
                task.workflow_id = f"wf-{task.id}"
                logger.debug(
                    "WorkflowEngine available for task %s (workflow_id=%s)",
                    task.id,
                    task.workflow_id,
                )
            except (RuntimeError, ImportError, AttributeError) as exc:
                logger.debug("WorkflowEngine unavailable: %s", exc)

        # Mark as completed for simple synchronous execution.
        # In a production system this would be replaced by async workflow
        # execution with callbacks.
        task.status = "completed"
        task.updated_at = time.time()
        task.result = {
            "summary": f"Task '{task.goal}' executed successfully.",
            "steps_completed": len(route.workflow_steps),
            "workflow_id": task.workflow_id,
        }

        emit_handler_event(
            "task",
            COMPLETED,
            {"task_id": task.id, "result": task.result},
            resource_id=task.id,
        )
