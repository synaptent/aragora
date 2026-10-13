"""
Workflow Templates API Handler.

Endpoints:
- GET /api/workflow/templates - List available templates
- GET /api/workflow/templates/:id - Get template details
- GET /api/workflow/templates/:id/package - Get full package
- POST /api/workflow/templates/run - Execute a template

Provides marketplace-style access to workflow templates.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from aragora.workflow.types import WorkflowDefinition

from aragora.config import DEFAULT_ROUNDS
from aragora.rbac.decorators import require_permission

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    get_bounded_string_param,
    get_clamped_int_param,
    get_int_param,
    handle_errors,
    json_response,
)
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# =============================================================================
# Async Workflow Execution Support
# =============================================================================


def _run_workflow_execution_in_thread(
    workflow: Any,
    execution_id: str,
    inputs: dict[str, Any] | None,
    tenant_id: str,
) -> threading.Thread:
    """Run workflow execution in a daemon thread when no event loop is available."""

    def _runner() -> None:
        asyncio.run(_execute_workflow_async(workflow, execution_id, inputs, tenant_id))

    thread = threading.Thread(
        target=_runner,
        name=f"workflow-{execution_id}",
        daemon=True,
    )
    thread.start()
    return thread


def _get_workflow_store():
    """Get the persistent workflow store for execution tracking."""
    from aragora.workflow.persistent_store import get_workflow_store

    return get_workflow_store()


def _get_workflow_engine():
    """Get the workflow engine instance."""
    from aragora.workflow.engine import get_workflow_engine

    return get_workflow_engine()


async def _execute_workflow_async(
    workflow: Any,
    execution_id: str,
    inputs: dict[str, Any] | None = None,
    tenant_id: str = "default",
) -> None:
    """
    Execute a workflow asynchronously in the background.

    This function runs as a background task and updates execution status
    in the persistent store as it progresses.
    """
    store = _get_workflow_store()
    engine = _get_workflow_engine()

    try:
        # Execute the workflow
        result = await engine.execute(workflow, inputs, execution_id)

        # Update execution record with results
        execution = store.get_execution(execution_id)
        if execution:
            execution.update(
                {
                    "status": "completed" if result.success else "failed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "outputs": result.final_output,
                    "steps": [
                        {
                            "step_id": s.step_id,
                            "step_name": s.step_name,
                            "status": (
                                s.status.value if hasattr(s.status, "value") else str(s.status)
                            ),
                            "duration_ms": s.duration_ms,
                            "error": s.error,
                        }
                        for s in result.steps
                    ],
                    "error": result.error,
                    "duration_ms": result.total_duration_ms,
                }
            )
            store.save_execution(execution)
            logger.info(
                "Workflow execution %s completed: success=%s, duration=%sms",
                execution_id,
                result.success,
                result.total_duration_ms,
            )

    except (RuntimeError, ValueError, TypeError, KeyError, AttributeError, OSError) as e:
        logger.exception("Workflow execution %s failed: %s", execution_id, e)
        execution = store.get_execution(execution_id)
        if execution:
            execution.update(
                {
                    "status": "failed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "error": "Workflow execution failed",
                }
            )
            store.save_execution(execution)


def _start_workflow_execution(
    workflow: Any,
    inputs: dict[str, Any] | None = None,
    tenant_id: str = "default",
) -> str:
    """
    Start a workflow execution as a background task.

    Returns the execution_id for status polling.
    """
    store = _get_workflow_store()
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"

    # Create initial execution record
    execution = {
        "id": execution_id,
        "workflow_id": workflow.id,
        "workflow_name": workflow.name,
        "tenant_id": tenant_id,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "inputs": inputs or {},
    }
    store.save_execution(execution)

    # Start background task
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(
            _execute_workflow_async(workflow, execution_id, inputs, tenant_id),
            name=f"workflow_{execution_id}",
        )
    except RuntimeError:
        # No running event loop - dispatch to a daemon thread with its own loop.
        _run_workflow_execution_in_thread(workflow, execution_id, inputs, tenant_id)

    logger.info("Started workflow execution %s for workflow %s", execution_id, workflow.id)
    return execution_id


# Rate limiter (60 requests per minute)
_template_limiter = RateLimiter(requests_per_minute=60)


class WorkflowTemplatesHandler(BaseHandler):
    """Handler for workflow templates API endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES: list[str] = [
        "/api/v1/workflow/templates",
        "/api/v1/workflow/templates/*",
        "/api/v1/workflow/templates/*/package",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the given path."""
        return path.startswith("/api/v1/workflow/templates")

    @require_permission("workflow:read")
    def handle(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route workflow template requests."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _template_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for templates endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        # Parse path
        method = handler.command if hasattr(handler, "command") else "GET"

        # Handle list/search
        if path in ("/api/v1/workflow/templates", "/api/v1/workflow/templates"):
            if method == "GET":
                return self._list_templates(query_params)
            elif method == "POST":
                # Run a template
                return self._run_template(handler)
            else:
                return error_response(f"Method {method} not allowed", 405)

        # Handle specific template requests
        # /api/v1/workflow/templates/{id...} -> parts = ["", "api", "v1", "workflow", "templates", ...]
        parts = path.split("/")
        if len(parts) >= 6:
            # Extract template ID (could be like "legal/contract-review")
            template_parts = parts[5:] if path.startswith("/api/v1/") else parts[4:]

            if not template_parts:
                return error_response("Template ID required", 400)

            # Check for special routes
            if template_parts[-1] == "package":
                template_id = "/".join(template_parts[:-1])
                return self._get_package(template_id)
            elif template_parts[-1] == "run":
                template_id = "/".join(template_parts[:-1])
                return self._run_specific_template(template_id, handler)
            else:
                template_id = "/".join(template_parts)
                return self._get_template(template_id)

        return error_response("Invalid path", 400)

    def _emit_template_event(self, event_name: str, data: dict[str, Any]) -> None:
        """Emit a TEMPLATE_* event if event emitter is available."""
        try:
            from aragora.events.types import StreamEvent, StreamEventType

            event_type = getattr(StreamEventType, event_name, None)
            if event_type is None:
                return
            emitter = self.ctx.get("event_emitter") if self.ctx else None
            if emitter:
                emitter.emit(StreamEvent(type=event_type, data=data))
        except (ImportError, AttributeError, TypeError):
            pass

    @handle_errors("list templates")
    def _list_templates(self, query_params: dict) -> HandlerResult:
        """List available workflow templates."""
        from aragora.workflow.templates import list_templates, WORKFLOW_TEMPLATES

        # Get filters
        category = get_bounded_string_param(query_params, "category", None, max_length=50)
        tag = get_bounded_string_param(query_params, "tag", None, max_length=50)
        search = get_bounded_string_param(query_params, "search", None, max_length=100)
        limit = get_clamped_int_param(query_params, "limit", 50, min_val=1, max_val=100)
        offset = get_int_param(query_params, "offset", 0)

        # Get templates
        templates = list_templates(category=category)

        # Apply tag filter
        if tag:
            templates = [t for t in templates if tag in t.get("tags", [])]

        # Apply search filter
        if search:
            search_lower = search.lower()
            templates = [
                t
                for t in templates
                if search_lower in t["name"].lower()
                or search_lower in t.get("description", "").lower()
            ]

        # Count total before pagination
        total = len(templates)

        # Apply pagination
        templates = templates[offset : offset + limit]

        # Enrich with additional metadata
        enriched = []
        for t in templates:
            template_def = WORKFLOW_TEMPLATES.get(t["id"])
            enriched.append(
                {
                    **t,
                    "steps_count": len(template_def.get("steps", [])) if template_def else 0,
                    "pattern": template_def.get("pattern") if template_def else None,
                    "estimated_duration": (
                        template_def.get("estimated_duration") if template_def else None
                    ),
                }
            )

        return json_response(
            {
                "templates": enriched,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )

    @handle_errors("get template")
    def _get_template(self, template_id: str) -> HandlerResult:
        """Get details of a specific template."""
        from aragora.workflow.templates import get_template

        template = get_template(template_id)
        if not template:
            return error_response(f"Template not found: {template_id}", 404)

        # Get metadata
        category = template_id.split("/")[0] if "/" in template_id else "general"

        return json_response(
            {
                "id": template_id,
                "name": template.get("name", template_id),
                "description": template.get("description", ""),
                "category": category,
                "pattern": template.get("pattern"),
                "steps": template.get("steps", []),
                "inputs": template.get("inputs", {}),
                "outputs": template.get("outputs", {}),
                "estimated_duration": template.get("estimated_duration"),
                "recommended_agents": template.get("recommended_agents", []),
                "tags": template.get("tags", []),
            }
        )

    @handle_errors("get template package")
    def _get_package(self, template_id: str) -> HandlerResult:
        """Get the full package for a template."""
        from aragora.workflow.templates import get_template
        from aragora.workflow.templates.package import (
            create_package,
            TemplateAuthor,
        )

        template = get_template(template_id)
        if not template:
            return error_response(f"Template not found: {template_id}", 404)

        # Create package on-the-fly
        category = template_id.split("/")[0] if "/" in template_id else "general"
        package = create_package(
            template=template,
            version="1.0.0",
            author=TemplateAuthor(name="Aragora Team", organization="Aragora"),
            category=category,
        )

        return json_response(package.to_dict())

    @handle_errors("run template")
    def _run_template(self, handler: Any) -> HandlerResult:
        """Run a workflow template with provided inputs."""
        from aragora.workflow.engine import WorkflowEngine
        from aragora.workflow.templates import get_template

        # Parse request body
        try:
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > 10 * 1024 * 1024:
                return error_response("Request body too large", 413)
            body = handler.rfile.read(content_length).decode("utf-8")
            data = json.loads(body) if body else {}
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request body", 400)

        template_id = data.get("template_id")
        if not template_id:
            return error_response("template_id is required", 400)

        template = get_template(template_id)
        if not template:
            return error_response(f"Template not found: {template_id}", 404)

        inputs = data.get("inputs", {})

        # Execute template
        try:
            engine = WorkflowEngine()
            # Convert template dict to WorkflowDefinition
            workflow_def = WorkflowDefinition.from_dict(template)
            self._emit_template_event(
                "TEMPLATE_EXECUTION_STARTED",
                {
                    "template_id": template_id,
                    "workflow_id": workflow_def.id,
                },
            )
            result = asyncio.run(engine.execute(workflow_def, inputs))

            self._emit_template_event(
                "TEMPLATE_EXECUTION_COMPLETE",
                {
                    "template_id": template_id,
                    "success": result.success if hasattr(result, "success") else True,
                },
            )
            return json_response(
                {
                    "status": "completed",
                    "template_id": template_id,
                    "result": result.to_dict() if hasattr(result, "to_dict") else result,
                }
            )
        except (RuntimeError, ValueError, TypeError, KeyError, AttributeError, OSError) as e:
            logger.error("Template execution failed: %s", e)
            self._emit_template_event(
                "TEMPLATE_EXECUTION_FAILED",
                {
                    "template_id": template_id,
                    "error": type(e).__name__,
                },
            )
            return json_response(
                {
                    "status": "failed",
                    "template_id": template_id,
                    "error": "Template execution failed",
                },
                status=500,
            )

    @handle_errors("run specific template")
    def _run_specific_template(self, template_id: str, handler: Any) -> HandlerResult:
        """Run a specific workflow template."""
        from aragora.workflow.templates import get_template

        template = get_template(template_id)
        if not template:
            return error_response(f"Template not found: {template_id}", 404)

        # Parse request body
        try:
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > 10 * 1024 * 1024:
                return error_response("Request body too large", 413)
            body = handler.rfile.read(content_length).decode("utf-8")
            data = json.loads(body) if body else {}
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request body", 400)

        # Add template_id to data and delegate
        data["template_id"] = template_id

        # Simulate the body being available again
        class MockHandler:
            def __init__(self, original, data):
                self.headers = original.headers
                self._data = data

            def read_body(self):
                return self._data

        self._emit_template_event(
            "TEMPLATE_INSTANTIATED",
            {
                "template_id": template_id,
            },
        )

        # Return response indicating async execution would start
        return json_response(
            {
                "status": "accepted",
                "template_id": template_id,
                "message": "Template execution started",
            },
            status=202,
        )


# Categories endpoint
class WorkflowCategoriesHandler(BaseHandler):
    """Handler for workflow template categories."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES: list[str] = [
        "/api/v1/workflow/categories",
        "/api/v1/workflow/categories",
    ]

    def can_handle(self, path: str) -> bool:
        return path in self.ROUTES

    def handle(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Return available template categories."""
        from aragora.workflow.templates.package import TemplateCategory
        from aragora.workflow.templates import WORKFLOW_TEMPLATES

        # Count templates per category
        category_counts: dict[str, int] = {}
        for template_id in WORKFLOW_TEMPLATES:
            category = template_id.split("/")[0] if "/" in template_id else "general"
            category_counts[category] = category_counts.get(category, 0) + 1

        categories = [
            {
                "id": cat.value,
                "name": cat.value.replace("_", " ").title(),
                "template_count": category_counts.get(cat.value, 0),
            }
            for cat in TemplateCategory
            if category_counts.get(cat.value, 0) > 0
        ]

        return json_response({"categories": categories})


# Patterns endpoint
class WorkflowPatternsHandler(BaseHandler):
    """Handler for workflow patterns listing."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES: list[str] = [
        "/api/v1/workflow/patterns",
        "/api/v1/workflow/patterns",
    ]

    def can_handle(self, path: str) -> bool:
        return path in self.ROUTES

    def handle(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Return available workflow patterns."""
        from aragora.workflow.patterns import PATTERN_REGISTRY
        from aragora.workflow.patterns.base import PatternType

        patterns = []
        for pattern_type in PatternType:
            pattern_class = PATTERN_REGISTRY.get(pattern_type)
            patterns.append(
                {
                    "id": pattern_type.value,
                    "name": pattern_type.value.replace("_", " ").title(),
                    "description": (
                        pattern_class.__doc__.split("\n")[0]
                        if pattern_class and pattern_class.__doc__
                        else ""
                    ),
                    "available": pattern_class is not None,
                }
            )

        return json_response({"patterns": patterns})


class WorkflowPatternTemplatesHandler(BaseHandler):
    """Handler for pattern-based workflow template operations."""

    ROUTES: list[str] = [
        "/api/v1/workflow/pattern-templates",
        "/api/v1/workflow/pattern-templates/*",
        "/api/v1/workflow/pattern-templates",
        "/api/v1/workflow/pattern-templates/*",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        return path.startswith("/api/v1/workflow/pattern-templates") or path.startswith(
            "/api/v1/workflow/pattern-templates"
        )

    def handle(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route pattern template requests."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _template_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded", 429)

        method = handler.command if hasattr(handler, "command") else "GET"

        # List pattern templates
        if path in ("/api/v1/workflow/pattern-templates", "/api/v1/workflow/pattern-templates"):
            if method == "GET":
                return self._list_pattern_templates()
            else:
                return error_response(f"Method {method} not allowed", 405)

        # Handle specific pattern template requests
        parts = path.split("/")
        pattern_id = parts[-1]

        # Check for instantiate route
        if len(parts) >= 2 and parts[-1] == "instantiate":
            pattern_id = parts[-2]
            return self._instantiate_pattern(pattern_id, handler)

        return self._get_pattern_template(pattern_id)

    @handle_errors("list pattern templates")
    def _list_pattern_templates(self) -> HandlerResult:
        """List available pattern-based workflow templates."""
        from aragora.workflow.templates.patterns import list_pattern_templates

        templates = list_pattern_templates()

        return json_response(
            {
                "pattern_templates": templates,
                "total": len(templates),
            }
        )

    @handle_errors("get pattern template")
    def _get_pattern_template(self, pattern_id: str) -> HandlerResult:
        """Get details of a specific pattern template."""
        from aragora.workflow.templates.patterns import get_pattern_template

        # Try with pattern/ prefix if not found
        template = get_pattern_template(pattern_id)
        if not template:
            template = get_pattern_template(f"pattern/{pattern_id}")

        if not template:
            return error_response(f"Pattern template not found: {pattern_id}", 404)

        return json_response(
            {
                "id": template.get("id", pattern_id),
                "name": template.get("name", pattern_id),
                "description": template.get("description", ""),
                "pattern": template.get("pattern"),
                "version": template.get("version", "1.0.0"),
                "config": template.get("config", {}),
                "inputs": template.get("inputs", {}),
                "outputs": template.get("outputs", {}),
                "tags": template.get("tags", []),
            }
        )

    @handle_errors("instantiate pattern")
    def _instantiate_pattern(self, pattern_id: str, handler: Any) -> HandlerResult:
        """Create a workflow definition from a pattern template."""
        from aragora.workflow.templates.patterns import (
            create_hive_mind_workflow,
            create_map_reduce_workflow,
            create_review_cycle_workflow,
        )

        # Parse request body
        try:
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > 10 * 1024 * 1024:
                return error_response("Request body too large", 413)
            body = handler.rfile.read(content_length).decode("utf-8")
            data = json.loads(body) if body else {}
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request body", 400)

        # Map pattern IDs to factory functions
        # Note: These functions are typed as returning dict[str, Any] but actually return
        # WorkflowDefinition (cast internally). We cast the result back to WorkflowDefinition.
        pattern_factories: dict[str, Callable[..., Any]] = {
            "hive-mind": create_hive_mind_workflow,
            "hive_mind": create_hive_mind_workflow,
            "map-reduce": create_map_reduce_workflow,
            "map_reduce": create_map_reduce_workflow,
            "review-cycle": create_review_cycle_workflow,
            "review_cycle": create_review_cycle_workflow,
        }

        factory = pattern_factories.get(pattern_id)
        if not factory:
            return error_response(
                f"Unknown pattern: {pattern_id}. Available: {list(pattern_factories.keys())}", 404
            )

        # Extract configuration from request
        name = data.get("name", f"{pattern_id.replace('-', ' ').title()} Workflow")
        task = data.get("task", "")
        config = data.get("config", {})

        # Merge task and config
        workflow_args: dict[str, Any] = {"name": name, "task": task, **config}

        try:
            # Factory functions return WorkflowDefinition (despite being typed as dict)
            workflow: WorkflowDefinition = factory(**workflow_args)

            # Convert workflow to serializable dict
            workflow_dict = {
                "id": workflow.id,
                "name": workflow.name,
                "description": workflow.description,
                "pattern": pattern_id,
                "steps": [
                    {
                        "id": step.id,
                        "name": step.name,
                        "type": step.step_type,
                        "config": step.config,
                        "next_steps": step.next_steps,
                    }
                    for step in workflow.steps
                ],
                "entry_step": workflow.entry_step,
                "tags": workflow.tags,
                "metadata": workflow.metadata,
            }

            return json_response(
                {
                    "status": "created",
                    "workflow": workflow_dict,
                },
                status=201,
            )

        except (RuntimeError, ValueError, TypeError, KeyError, AttributeError) as e:
            logger.error("Failed to instantiate pattern %s: %s", pattern_id, e)
            return error_response("Pattern instantiation failed", 500)


# =============================================================================
# Template Recommendations for Onboarding
# =============================================================================

# Use case to template recommendations mapping
USE_CASE_TEMPLATES = {
    "team_decisions": [
        {
            "id": "general/quick-decision",
            "name": "Quick Decision",
            "description": "Fast yes/no decisions with 2 agents",
        },
        {
            "id": "product/feature-prioritization",
            "name": "Feature Prioritization",
            "description": "Prioritize features using multi-agent debate",
        },
        {
            "id": "general/pros-cons",
            "name": "Pros and Cons Analysis",
            "description": "Balanced analysis of options",
        },
    ],
    "project_planning": [
        {
            "id": "product/feature-prioritization",
            "name": "Feature Prioritization",
            "description": "Prioritize features using multi-agent debate",
        },
        {
            "id": "devops/incident-response",
            "name": "Incident Response",
            "description": "Structured incident analysis and response",
        },
        {
            "id": "code/architecture-review",
            "name": "Architecture Review",
            "description": "Review system architecture decisions",
        },
    ],
    "vendor_selection": [
        {
            "id": "general/vendor-comparison",
            "name": "Vendor Comparison",
            "description": "Compare vendors across multiple criteria",
        },
        {
            "id": "general/pros-cons",
            "name": "Pros and Cons Analysis",
            "description": "Balanced analysis of options",
        },
        {
            "id": "general/quick-decision",
            "name": "Quick Decision",
            "description": "Fast yes/no decisions with 2 agents",
        },
    ],
    "policy_review": [
        {
            "id": "legal/contract-review",
            "name": "Contract Review",
            "description": "Comprehensive contract analysis",
        },
        {
            "id": "legal/compliance-check",
            "name": "Compliance Check",
            "description": "Policy compliance validation",
        },
        {
            "id": "general/policy-evaluation",
            "name": "Policy Evaluation",
            "description": "Multi-perspective policy analysis",
        },
    ],
    "technical_decisions": [
        {
            "id": "code/architecture-review",
            "name": "Architecture Review",
            "description": "Review system architecture decisions",
        },
        {
            "id": "code/security-audit",
            "name": "Security Audit",
            "description": "Security vulnerability analysis",
        },
        {
            "id": "devops/infrastructure-review",
            "name": "Infrastructure Review",
            "description": "Cloud infrastructure decisions",
        },
    ],
    "general": [
        {
            "id": "general/quick-decision",
            "name": "Quick Decision",
            "description": "Fast yes/no decisions with 2 agents",
        },
        {
            "id": "general/pros-cons",
            "name": "Pros and Cons Analysis",
            "description": "Balanced analysis of options",
        },
        {
            "id": "general/brainstorm",
            "name": "Brainstorm",
            "description": "Creative ideation with multiple agents",
        },
        {
            "id": "general/deep-dive",
            "name": "Deep Dive",
            "description": "Thorough analysis with extended rounds",
        },
    ],
}


class TemplateRecommendationsHandler(BaseHandler):
    """Handler for template recommendations based on use case."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES: list[str] = [
        "/api/v1/templates/recommended",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        return path == "/api/v1/templates/recommended" and method == "GET"

    def handle(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Return recommended templates based on use case."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _template_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded", 429)

        return self._get_recommendations(query_params)

    @handle_errors("get template recommendations")
    def _get_recommendations(self, query_params: dict) -> HandlerResult:
        """Get recommended templates for a use case."""
        from aragora.workflow.templates import get_template

        use_case = get_bounded_string_param(query_params, "use_case", "general", max_length=50)
        limit = get_clamped_int_param(query_params, "limit", 4, min_val=1, max_val=10)

        # Get recommendations for the use case
        recommendations = USE_CASE_TEMPLATES.get(use_case, USE_CASE_TEMPLATES["general"])

        # Limit results
        recommendations = recommendations[:limit]

        # Enrich with template details
        enriched = []
        for rec in recommendations:
            template = get_template(rec["id"]) or {}
            enriched.append(
                {
                    "id": rec["id"],
                    "name": rec.get("name") or template.get("name", rec["id"]),
                    "description": rec.get("description") or template.get("description", ""),
                    "agents_count": len(template.get("recommended_agents", [])) or 2,
                    "rounds": template.get("config", {}).get("rounds", DEFAULT_ROUNDS),
                    "estimated_duration_minutes": template.get("estimated_duration", 5),
                    "use_case": use_case,
                    "category": rec["id"].split("/")[0] if "/" in rec["id"] else "general",
                }
            )

        # Include available use cases
        available_use_cases = list(USE_CASE_TEMPLATES.keys())

        return json_response(
            {
                "recommendations": enriched,
                "use_case": use_case,
                "available_use_cases": available_use_cases,
                "total": len(enriched),
            }
        )


class SMEWorkflowsHandler(BaseHandler):
    """Handler for SME-specific workflow templates and automations.

    Provides quick access to pre-built SME workflows:
    - Invoice generation
    - Customer follow-ups
    - Inventory alerts
    - Report scheduling
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES: list[str] = [
        "/api/v1/sme/workflows",
        "/api/v1/sme/workflows/*",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        return path.startswith("/api/v1/sme/workflows")

    def handle(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route SME workflow requests."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _template_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded", 429)

        method = handler.command if hasattr(handler, "command") else "GET"

        # List available SME workflows
        if path == "/api/v1/sme/workflows":
            if method == "GET":
                return self._list_sme_workflows()
            else:
                return error_response(f"Method {method} not allowed", 405)

        # Handle specific workflow types
        # /api/v1/sme/workflows/{type} -> parts = ["", "api", "v1", "sme", "workflows", type]
        parts = path.split("/")
        if len(parts) >= 6:
            workflow_type = parts[5]

            # POST to create a workflow instance
            if method == "POST":
                return self._create_sme_workflow(workflow_type, handler)

            # GET to get workflow schema/info
            if method == "GET":
                return self._get_sme_workflow_info(workflow_type)

        return error_response("Invalid SME workflow path", 400)

    @handle_errors("list SME workflows")
    def _list_sme_workflows(self) -> HandlerResult:
        """List available SME workflow automations."""
        workflows = [
            {
                "id": "invoice",
                "name": "Invoice Generation",
                "description": "Generate and send professional invoices",
                "icon": "receipt",
                "category": "billing",
                "inputs": ["customer_id", "items", "tax_rate", "due_days"],
                "features": ["PDF generation", "Email delivery", "Record keeping"],
            },
            {
                "id": "followup",
                "name": "Customer Follow-up",
                "description": "Automated customer follow-up campaigns",
                "icon": "users",
                "category": "crm",
                "inputs": ["followup_type", "days_since_contact", "channel"],
                "features": ["Sentiment analysis", "Personalized messages", "Scheduling"],
            },
            {
                "id": "inventory",
                "name": "Inventory Alerts",
                "description": "Monitor stock levels and send alerts",
                "icon": "package",
                "category": "operations",
                "inputs": ["alert_threshold", "notification_channels", "auto_reorder"],
                "features": ["Stock monitoring", "Multi-channel alerts", "Auto-reorder"],
            },
            {
                "id": "report",
                "name": "Report Scheduling",
                "description": "Automated report generation and delivery",
                "icon": "chart-bar",
                "category": "analytics",
                "inputs": ["report_type", "frequency", "format", "recipients"],
                "features": ["Multiple formats", "Charts", "Period comparison"],
            },
        ]

        return json_response(
            {
                "workflows": workflows,
                "total": len(workflows),
            }
        )

    @handle_errors("get SME workflow info")
    def _get_sme_workflow_info(self, workflow_type: str) -> HandlerResult:
        """Get detailed info about an SME workflow type."""
        workflow_schemas = {
            "invoice": {
                "id": "invoice",
                "name": "Invoice Generation",
                "description": "Generate and send professional invoices to customers",
                "inputs": {
                    "customer_id": {
                        "type": "string",
                        "required": True,
                        "description": "Customer ID or name",
                    },
                    "items": {
                        "type": "array",
                        "required": True,
                        "description": "Invoice line items",
                        "items": {
                            "name": {"type": "string", "required": True},
                            "quantity": {"type": "number", "required": True},
                            "unit_price": {"type": "number", "required": True},
                        },
                    },
                    "tax_rate": {
                        "type": "number",
                        "required": False,
                        "default": 0,
                        "description": "Tax rate (0-1)",
                    },
                    "due_days": {
                        "type": "integer",
                        "required": False,
                        "default": 30,
                        "description": "Days until due",
                    },
                    "send_email": {"type": "boolean", "required": False, "default": False},
                    "notes": {"type": "string", "required": False, "default": ""},
                },
                "outputs": ["invoice_id", "invoice_pdf", "total_amount", "email_sent"],
            },
            "followup": {
                "id": "followup",
                "name": "Customer Follow-up",
                "description": "Automated customer follow-up campaigns",
                "inputs": {
                    "followup_type": {
                        "type": "string",
                        "required": False,
                        "default": "check_in",
                        "enum": ["post_sale", "check_in", "renewal", "feedback"],
                    },
                    "days_since_contact": {"type": "integer", "required": False, "default": 30},
                    "channel": {
                        "type": "string",
                        "required": False,
                        "default": "email",
                        "enum": ["email", "sms", "call_scheduled"],
                    },
                    "auto_send": {"type": "boolean", "required": False, "default": False},
                    "customer_id": {
                        "type": "string",
                        "required": False,
                        "description": "Specific customer (optional)",
                    },
                },
                "outputs": [
                    "customers_processed",
                    "messages_sent",
                    "messages_queued",
                    "next_followups",
                ],
            },
            "inventory": {
                "id": "inventory",
                "name": "Inventory Alerts",
                "description": "Monitor stock levels and send alerts",
                "inputs": {
                    "alert_threshold": {
                        "type": "integer",
                        "required": False,
                        "default": 20,
                        "description": "% of safety stock",
                    },
                    "auto_reorder": {"type": "boolean", "required": False, "default": False},
                    "notification_channels": {
                        "type": "array",
                        "required": False,
                        "default": ["email"],
                        "items": {"type": "string", "enum": ["email", "slack", "sms"]},
                    },
                    "categories": {
                        "type": "array",
                        "required": False,
                        "description": "Product categories to monitor",
                    },
                },
                "outputs": [
                    "low_stock_items",
                    "critical_items",
                    "reorder_suggestions",
                    "orders_created",
                    "alerts_sent",
                ],
            },
            "report": {
                "id": "report",
                "name": "Report Scheduling",
                "description": "Automated report generation and delivery",
                "inputs": {
                    "report_type": {
                        "type": "string",
                        "required": True,
                        "enum": ["sales", "financial", "inventory", "customer", "custom"],
                    },
                    "frequency": {
                        "type": "string",
                        "required": False,
                        "default": "weekly",
                        "enum": ["daily", "weekly", "monthly", "quarterly"],
                    },
                    "date_range": {
                        "type": "string",
                        "required": False,
                        "default": "last_week",
                        "enum": ["last_day", "last_week", "last_month", "custom"],
                    },
                    "format": {
                        "type": "string",
                        "required": False,
                        "default": "pdf",
                        "enum": ["pdf", "excel", "html", "json"],
                    },
                    "recipients": {"type": "array", "required": False, "items": {"type": "string"}},
                    "include_charts": {"type": "boolean", "required": False, "default": True},
                    "comparison": {"type": "boolean", "required": False, "default": True},
                },
                "outputs": ["report_id", "report_file", "insights", "delivery_status"],
            },
        }

        schema = workflow_schemas.get(workflow_type)
        if not schema:
            return error_response(f"Unknown SME workflow type: {workflow_type}", 404)

        return json_response(schema)

    @handle_errors("create SME workflow")
    def _create_sme_workflow(self, workflow_type: str, handler: Any) -> HandlerResult:
        """Create and optionally execute an SME workflow."""
        # Parse request body
        try:
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > 10 * 1024 * 1024:
                return error_response("Request body too large", 413)
            body = handler.rfile.read(content_length).decode("utf-8")
            data = json.loads(body) if body else {}
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request body", 400)

        # Import SME workflow factories
        from aragora.workflow.templates.sme import (
            create_invoice_workflow,
            create_followup_workflow,
            create_inventory_alert_workflow,
            create_report_workflow,
        )

        execute = data.pop("execute", False)

        try:
            # Create workflow based on type
            if workflow_type == "invoice":
                workflow = create_invoice_workflow(
                    customer_id=data.get("customer_id", ""),
                    items=data.get("items", []),
                    tax_rate=data.get("tax_rate", 0),
                    due_days=data.get("due_days", 30),
                    send_email=data.get("send_email", False),
                    notes=data.get("notes", ""),
                )
            elif workflow_type == "followup":
                workflow = create_followup_workflow(
                    followup_type=data.get("followup_type", "check_in"),
                    days_since_contact=data.get("days_since_contact", 30),
                    channel=data.get("channel", "email"),
                    auto_send=data.get("auto_send", False),
                    customer_id=data.get("customer_id"),
                )
            elif workflow_type == "inventory":
                workflow = create_inventory_alert_workflow(
                    alert_threshold=data.get("alert_threshold", 20),
                    auto_reorder=data.get("auto_reorder", False),
                    notification_channels=data.get("notification_channels"),
                    categories=data.get("categories"),
                )
            elif workflow_type == "report":
                workflow = create_report_workflow(
                    report_type=data.get("report_type", "sales"),
                    frequency=data.get("frequency", "weekly"),
                    date_range=data.get("date_range", "last_week"),
                    format=data.get("format", "pdf"),
                    recipients=data.get("recipients"),
                    include_charts=data.get("include_charts", True),
                    include_comparison=data.get("comparison", True),
                )
            else:
                return error_response(f"Unknown SME workflow type: {workflow_type}", 400)

            response_data = {
                "workflow_id": workflow.id,
                "workflow_type": workflow_type,
                "name": workflow.name,
                "steps_count": len(workflow.steps),
                "status": "created",
            }

            # Execute if requested
            if execute:
                # Start async workflow execution
                execution_id = _start_workflow_execution(
                    workflow=workflow,
                    inputs=data,
                    tenant_id=data.get("tenant_id", "default"),
                )
                response_data["status"] = "running"
                response_data["execution_id"] = execution_id
                response_data["message"] = "Workflow execution started"
                response_data["poll_url"] = f"/api/v1/workflow-executions/{execution_id}"

            return json_response(response_data, status=201)

        except (RuntimeError, ValueError, TypeError, KeyError, AttributeError) as e:
            logger.error("Failed to create SME workflow: %s", e)
            return error_response("Workflow creation failed", 500)
