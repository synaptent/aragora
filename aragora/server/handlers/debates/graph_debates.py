"""
Graph debates endpoint handlers.

Endpoints:
- GET /api/debates/graph - List recent graph debates for the live browser
- POST /api/debates/graph - Run a graph-structured debate with branching
- GET /api/debates/graph/{id} - Get graph debate by ID
- GET /api/debates/graph/{id}/branches - Get all branches for a debate
- GET /api/debates/graph/{id}/nodes - Get all nodes in debate graph
"""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import inspect
import logging
import re
from typing import Any, cast

from aragora.config import DEFAULT_ROUNDS
from aragora.agents.base import AgentType
from ..base import (
    MaybeAsyncHandlerResult,
    SAFE_AGENT_PATTERN,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
    safe_error_message,
)
from ..openapi_decorator import api_endpoint
from ..secure import SecureHandler, ForbiddenError, UnauthorizedError
from aragora.server.versioning.compat import strip_version_prefix

# Suspicious patterns for task sanitization
_SUSPICIOUS_PATTERNS = [
    re.compile(r"<script", re.IGNORECASE),
    re.compile(r"javascript:", re.IGNORECASE),
    re.compile(r"\x00"),  # Null byte injection
    re.compile(r"\{\{.*\}\}"),  # Template injection
]
from ..utils.rate_limit import RateLimiter, get_client_ip
from aragora.resilience import with_timeout
from aragora.rbac.decorators import require_permission
from aragora.tenancy.record_scope import (
    OrgScope,
    record_not_found,
    record_visible,
    require_org_scope,
)

logger = logging.getLogger(__name__)

# RBAC permissions for graph debates
DEBATES_READ_PERMISSION = "debates:read"
DEBATES_WRITE_PERMISSION = "debates:create"

# Rate limiter for graph debates (5 requests per minute - branching debates are expensive)
_graph_limiter = RateLimiter(requests_per_minute=5)
_GRAPH_DEBATE_CACHE_LIMIT = 100
_graph_debate_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()


def _graph_debate_created_at(debate: dict[str, Any]) -> str:
    """Return an ISO timestamp for graph debate sorting and responses."""
    created_at = debate.get("created_at")
    if isinstance(created_at, str) and created_at:
        return created_at

    graph = debate.get("graph")
    if isinstance(graph, dict):
        graph_created_at = graph.get("created_at")
        if isinstance(graph_created_at, str) and graph_created_at:
            return graph_created_at

    return datetime.now(timezone.utc).isoformat()


def _normalize_graph_debate_payload(debate: dict[str, Any]) -> dict[str, Any]:
    """Ensure cached/listed graph debates share a stable shape."""
    normalized = deepcopy(debate)
    normalized.setdefault("created_at", _graph_debate_created_at(normalized))
    normalized.setdefault("status", "completed")

    graph = normalized.get("graph")
    if isinstance(graph, dict):
        branches = graph.get("branches")
        if normalized.get("branches") is None and isinstance(branches, dict):
            normalized["branches"] = list(branches.values())

    return normalized


async def _maybe_await(result: Any) -> Any:
    """Await async storage hooks while also accepting sync fallbacks."""
    if inspect.isawaitable(result):
        return await result
    return result


def _remember_graph_debate(debate: dict[str, Any]) -> dict[str, Any]:
    """Store a graph debate in the in-process cache for live UI retrieval."""
    normalized = _normalize_graph_debate_payload(debate)
    debate_id = str(normalized.get("debate_id") or "").strip()
    if not debate_id:
        return normalized

    _graph_debate_cache[debate_id] = normalized
    _graph_debate_cache.move_to_end(debate_id)
    while len(_graph_debate_cache) > _GRAPH_DEBATE_CACHE_LIMIT:
        _graph_debate_cache.popitem(last=False)
    return normalized


def _get_cached_graph_debate(debate_id: str) -> dict[str, Any] | None:
    """Return a cached graph debate by ID if one exists."""
    debate = _graph_debate_cache.get(debate_id)
    return deepcopy(debate) if debate is not None else None


def _graph_debate_visible(debate: Any, scope: OrgScope) -> bool:
    return isinstance(debate, dict) and record_visible(debate.get("org_id"), scope)


def _list_cached_graph_debates(limit: int = 20) -> list[dict[str, Any]]:
    """Return cached graph debates newest-first."""
    debates = list(reversed(_graph_debate_cache.values()))
    if limit >= 0:
        debates = debates[:limit]
    return [deepcopy(debate) for debate in debates]


class GraphDebatesHandler(SecureHandler):
    """Handler for graph debate endpoints.

    RBAC Protected:
    - debates:read - required for GET endpoints
    - debates:create - required for POST endpoints
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/v1/debates/graph",
        "/api/v1/debates/graph/",
        "/api/v1/graph-debates",
        "/api/v1/graph-debates/",
        "/api/v1/graph-debates/*",
    ]

    AUTH_REQUIRED_ENDPOINTS = [
        "/api/v1/debates/graph",
        "/api/v1/graph-debates",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        normalized = strip_version_prefix(path)
        return normalized.startswith("/api/debates/graph") or normalized.startswith(
            "/api/graph-debates"
        )

    def handle(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> MaybeAsyncHandlerResult:
        """Route GET requests through the async handler."""
        return self.handle_get(handler, path, query_params)

    @api_endpoint(
        method="GET",
        path="/api/v1/debates/graph/{debate_id}",
        summary="Get graph debate",
        description="Get a graph-structured debate by ID, including branches and nodes.",
        tags=["Debates", "Graph Debates"],
        parameters=[
            {"name": "debate_id", "in": "path", "required": True, "schema": {"type": "string"}}
        ],
        responses={
            "200": {"description": "Graph debate details"},
            "401": {"description": "Authentication required"},
            "403": {"description": "Permission denied"},
            "404": {"description": "Graph debate not found"},
        },
        operation_id="get_graph_debate",
    )
    @require_permission(DEBATES_READ_PERMISSION)
    @handle_errors("graph debates GET")
    async def handle_get(self, handler: Any, path: str, query_params: dict) -> HandlerResult:
        """Handle GET requests for graph debates with RBAC."""
        scope, scope_error = require_org_scope(handler)
        if scope is None:
            return scope_error

        # RBAC: Require authentication and debates:read permission
        try:
            auth_context = await self.get_auth_context(handler, require_auth=True)
            self.check_permission(auth_context, DEBATES_READ_PERMISSION)
        except UnauthorizedError:
            return error_response("Authentication required", 401)
        except ForbiddenError as e:
            logger.warning("Graph debates GET access denied: %s", e)
            return error_response("Permission denied", 403)

        # Extract debate ID from path if present
        normalized = strip_version_prefix(path)
        if normalized.startswith("/api/graph-debates"):
            normalized = normalized.replace("/api/graph-debates", "/api/debates/graph", 1)
        parts = normalized.rstrip("/").split("/")

        if normalized.rstrip("/") == "/api/debates/graph":
            return await self._list_graph_debates(handler, query_params, scope)

        # GET /api/debates/graph/{id} - Get specific graph debate
        # Path structure: ['', 'api', 'debates', 'graph', '{id}', ...]
        if len(parts) >= 5 and parts[3] == "graph":
            debate_id = parts[4]

            # GET /api/v1/debates/graph/{id}/branches
            if len(parts) >= 6 and parts[5] == "branches":
                return await self._get_branches(handler, debate_id, scope)

            # GET /api/v1/debates/graph/{id}/nodes
            if len(parts) >= 6 and parts[5] == "nodes":
                return await self._get_nodes(handler, debate_id, scope)

            return await self._get_graph_debate(handler, debate_id, scope)

        return error_response("Not found", 404)

    @api_endpoint(
        method="POST",
        path="/api/v1/debates/graph",
        summary="Create graph debate",
        description="Run a new graph-structured debate with automatic branching on disagreement.",
        tags=["Debates", "Graph Debates"],
        operation_id="create_graph_debate",
        responses={
            "200": {"description": "Graph debate created and executed"},
            "400": {"description": "Invalid request body"},
            "401": {"description": "Authentication required"},
            "403": {"description": "Permission denied"},
            "429": {"description": "Rate limit exceeded"},
            "500": {"description": "Graph debate module not available"},
        },
    )
    @require_permission(DEBATES_WRITE_PERMISSION)
    @handle_errors("graph debates POST")
    async def handle_post(self, *args: Any, **kwargs: Any) -> HandlerResult:
        """Handle POST requests for graph debates with RBAC.

        POST /api/debates/graph - Run a new graph debate
        """
        handler = None
        path = ""
        data: dict = {}
        read_body = False

        if len(args) >= 3:
            if isinstance(args[0], str):
                path = args[0]
                handler = args[2]
                read_body = True
            else:
                handler = args[0]
                path = args[1]
                data = args[2] or {}
        else:
            handler = kwargs.get("handler")
            path = kwargs.get("path", "")
            data = kwargs.get("data") or kwargs.get("body") or {}
            if handler is None:
                return error_response("Invalid request", 400)
            read_body = not data

        scope, scope_error = require_org_scope(handler)
        if scope is None:
            return scope_error

        if read_body:
            data, error = self.read_json_body_validated(handler)
            if error:
                return error

        normalized = strip_version_prefix(path)
        if normalized.startswith("/api/graph-debates"):
            normalized = normalized.replace("/api/graph-debates", "/api/debates/graph", 1)
        if not normalized.rstrip("/").endswith("/debates/graph"):
            return error_response("Not found", 404)

        # RBAC: Require authentication and debates:create permission
        try:
            auth_context = await self.get_auth_context(handler, require_auth=True)
            self.check_permission(auth_context, DEBATES_WRITE_PERMISSION)
        except UnauthorizedError:
            return error_response("Authentication required", 401)
        except ForbiddenError as e:
            logger.warning("Graph debates POST access denied: %s", e)
            return error_response("Permission denied", 403)

        # Rate limit check (5/min - expensive branching operations)
        client_ip = get_client_ip(handler)
        if not _graph_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for graph debates: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        logger.debug("POST /api/debates/graph - running graph debate")
        return await self._run_graph_debate(handler, data, scope)

    @with_timeout(180.0)
    async def _run_graph_debate(self, handler: Any, data: dict, scope: OrgScope) -> HandlerResult:
        """Run a graph-structured debate with automatic branching.

        Request body:
            task: str - The debate topic/question (10-5000 chars)
            agents: list[str] - Agent names to participate (2-10 agents)
            max_rounds: int - Maximum rounds per branch (1-20, default: 5)
            branch_policy: dict - Custom branch policy settings
        """
        # Validate task (accept "question" as alias for frontend compatibility)
        task = data.get("task") or data.get("question")
        if not task:
            return error_response("task is required", 400)
        if not isinstance(task, str):
            return error_response("task must be a string", 400)
        task = task.strip()
        if len(task) < 10:
            return error_response("task must be at least 10 characters", 400)
        if len(task) > 5000:
            return error_response("task must be at most 5000 characters", 400)

        # Check for suspicious patterns in task (injection prevention)
        for pattern in _SUSPICIOUS_PATTERNS:
            if pattern.search(task):
                return error_response("task contains invalid characters", 400)

        # Validate agents
        agent_names = data.get("agents", [])
        if not isinstance(agent_names, list):
            return error_response("agents must be an array", 400)
        if len(agent_names) < 2:
            return error_response("At least 2 agents required for a debate", 400)
        if len(agent_names) > 10:
            return error_response("Maximum 10 agents allowed", 400)
        # Validate each agent name using security pattern
        for i, name in enumerate(agent_names):
            if not isinstance(name, str):
                return error_response(f"agents[{i}] must be a string", 400)
            if len(name) > 50:
                return error_response(f"agents[{i}] name too long (max 50 chars)", 400)
            if not SAFE_AGENT_PATTERN.match(name):
                return error_response(
                    f"agents[{i}]: invalid agent name (alphanumeric, hyphens, underscores only)",
                    400,
                )

        # Validate max_rounds
        max_rounds = data.get("max_rounds", DEFAULT_ROUNDS)
        if not isinstance(max_rounds, int):
            try:
                max_rounds = int(max_rounds)
            except (ValueError, TypeError):
                return error_response("max_rounds must be an integer", 400)
        if max_rounds < 1:
            return error_response("max_rounds must be at least 1", 400)
        if max_rounds > 20:
            return error_response("max_rounds must be at most 20", 400)

        # Validate branch_policy
        branch_policy_data = data.get("branch_policy", {})
        if not isinstance(branch_policy_data, dict):
            return error_response("branch_policy must be an object", 400)

        # Validate branch_policy fields
        if "min_disagreement" in branch_policy_data:
            min_dis = branch_policy_data["min_disagreement"]
            if not isinstance(min_dis, (int, float)) or min_dis < 0 or min_dis > 1:
                return error_response("branch_policy.min_disagreement must be 0-1", 400)
        if "max_branches" in branch_policy_data:
            max_br = branch_policy_data["max_branches"]
            if not isinstance(max_br, int) or max_br < 1 or max_br > 10:
                return error_response("branch_policy.max_branches must be 1-10", 400)
        if "merge_strategy" in branch_policy_data:
            strategy = branch_policy_data["merge_strategy"]
            if strategy not in ["synthesis", "vote", "best"]:
                return error_response(
                    "branch_policy.merge_strategy must be 'synthesis', 'vote', or 'best'", 400
                )

        try:
            import uuid

            from aragora.debate.graph import (
                BranchPolicy,
                GraphDebateOrchestrator,
            )

            # Load agents
            agents = await self._load_agents(agent_names)
            if not agents:
                return error_response("No valid agents found", 400)

            # Create branch policy
            policy = BranchPolicy(
                disagreement_threshold=branch_policy_data.get("min_disagreement", 0.7),
                max_branches=branch_policy_data.get("max_branches", 3),
                auto_merge_on_convergence=branch_policy_data.get("auto_merge", True),
            )

            # Create orchestrator
            orchestrator = GraphDebateOrchestrator(agents=agents, policy=policy)

            # Generate debate ID
            debate_id = str(uuid.uuid4())

            # Get event emitter if available
            event_emitter = getattr(handler, "event_emitter", None)

            # Define run_agent function
            async def run_agent(agent: Any, prompt: str, context: list[Any]) -> str:
                from aragora.server.stream.arena_hooks import streaming_task_context

                agent_name = getattr(agent, "name", "graph-agent")
                task_id = f"{agent_name}:graph_debate"
                with streaming_task_context(task_id):
                    return await agent.generate(prompt, context)

            # Run the debate
            graph = await orchestrator.run_debate(
                task=task,
                max_rounds=max_rounds,
                run_agent_fn=run_agent,
                event_emitter=event_emitter,
                debate_id=debate_id,
            )

            # Convert to response format
            graph_dict = graph.to_dict()
            debate_payload = {
                "debate_id": debate_id,
                "task": task,
                "status": "completed",
                "created_at": graph_dict.get("created_at")
                or datetime.now(timezone.utc).isoformat(),
                "graph": graph_dict,
                "branches": [b.to_dict() for b in graph.branches.values()],
                "merge_results": [
                    {
                        "merged_node_id": m.merged_node_id,
                        "source_branch_ids": m.source_branch_ids,
                        "strategy": m.strategy.value,
                        "conflicts_resolved": m.conflicts_resolved,
                        "insights_preserved": m.insights_preserved,
                    }
                    for m in graph.merge_history
                ],
                "node_count": len(graph.nodes),
                "branch_count": len(graph.branches),
                "org_id": scope.org_id,
                "created_by": scope.user_id,
            }
            await self._persist_graph_debate(handler, debate_payload)
            return json_response(debate_payload)

        except ImportError as e:
            logger.error("Import error for graph debates: %s", e)
            return error_response("Graph debate module not available", 500)
        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError, OSError) as e:
            logger.exception("Graph debate failed: %s", e)
            return error_response(safe_error_message(e, "graph debate"), 500)

    async def _load_agents(self, agent_names: list[str]) -> list:
        """Load agents by name."""
        try:
            from aragora.agents import create_agent

            agents = []
            for name in agent_names or ["claude", "gpt4"]:
                try:
                    # Cast to AgentType - validation already done in handle_post
                    agent = create_agent(model_type=cast(AgentType, name), name=name)
                    agents.append(agent)
                except (ImportError, ValueError, TypeError, KeyError, AttributeError) as e:
                    logger.warning("Failed to create agent %s: %s", name, e)
            return agents
        except (ImportError, ValueError, TypeError) as e:
            logger.warning("Failed to load agents: %s", e)
            return []

    async def _persist_graph_debate(self, handler: Any, debate: dict[str, Any]) -> None:
        """Persist completed graph debates via storage when available and cache otherwise."""
        cached = _remember_graph_debate(debate)

        storage = getattr(handler, "storage", None)
        save_graph_debate = getattr(storage, "save_graph_debate", None)
        if not callable(save_graph_debate):
            return

        try:
            await _maybe_await(save_graph_debate(cached))
        except (KeyError, ValueError, OSError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning("Failed to persist graph debate %s: %s", cached.get("debate_id"), e)

    async def _list_graph_debates(
        self, handler: Any, query_params: dict, scope: OrgScope
    ) -> HandlerResult:
        """List recently available graph debates for the live graph browser."""
        limit_raw = query_params.get("limit", 20)
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            return error_response("limit must be an integer", 400)
        if limit < 1 or limit > 100:
            return error_response("limit must be between 1 and 100", 400)

        combined: dict[str, dict[str, Any]] = {}

        storage = getattr(handler, "storage", None)
        list_graph_debates = getattr(storage, "list_graph_debates", None)
        if callable(list_graph_debates):
            try:
                stored = await _maybe_await(list_graph_debates(limit=limit))
                for debate in stored or []:
                    if not _graph_debate_visible(debate, scope):
                        continue
                    normalized = _remember_graph_debate(debate)
                    debate_id = normalized.get("debate_id")
                    if isinstance(debate_id, str) and debate_id:
                        combined[debate_id] = normalized
            except (KeyError, ValueError, OSError, TypeError, AttributeError, RuntimeError) as e:
                logger.warning("Failed to list graph debates from storage: %s", e)

        for debate in _list_cached_graph_debates(limit=-1):
            if not _graph_debate_visible(debate, scope):
                continue
            debate_id = debate.get("debate_id")
            if isinstance(debate_id, str) and debate_id and debate_id not in combined:
                combined[debate_id] = debate

        debates = sorted(combined.values(), key=_graph_debate_created_at, reverse=True)[:limit]
        return json_response({"debates": debates})

    async def _resolve_graph_debate(
        self, handler: Any, debate_id: str, scope: OrgScope
    ) -> dict[str, Any] | None:
        """Return the graph debate when it belongs to the caller's org, else None."""
        debate: Any = None
        storage = getattr(handler, "storage", None)
        if storage and callable(getattr(storage, "get_graph_debate", None)):
            try:
                debate = await _maybe_await(storage.get_graph_debate(debate_id))
            except (KeyError, ValueError, OSError, TypeError, AttributeError) as e:
                logger.warning("Failed to get graph debate %s from storage: %s", debate_id, e)
                debate = None
        if debate:
            if not _graph_debate_visible(debate, scope):
                return None
            return _remember_graph_debate(debate)

        debate = _get_cached_graph_debate(debate_id)
        return debate if _graph_debate_visible(debate, scope) else None

    async def _get_graph_debate(
        self, handler: Any, debate_id: str, scope: OrgScope
    ) -> HandlerResult:
        """Get a graph debate by ID."""
        debate = await self._resolve_graph_debate(handler, debate_id, scope)
        if debate is None:
            return record_not_found("Graph debate")
        return json_response(debate)

    @api_endpoint(
        method="GET",
        path="/api/v1/debates/graph/{debate_id}/branches",
        summary="Get graph debate branches",
        description="Get all branches created during a graph-structured debate.",
        tags=["Debates", "Graph Debates"],
        parameters=[
            {"name": "debate_id", "in": "path", "required": True, "schema": {"type": "string"}}
        ],
        responses={
            "200": {"description": "List of debate branches"},
            "401": {"description": "Authentication required"},
            "503": {"description": "Storage not configured"},
        },
    )
    async def _get_branches(self, handler: Any, debate_id: str, scope: OrgScope) -> HandlerResult:
        """Get all branches for a graph debate."""
        debate = await self._resolve_graph_debate(handler, debate_id, scope)
        if debate is None:
            return record_not_found("Graph debate")

        storage = getattr(handler, "storage", None)
        if storage and callable(getattr(storage, "get_debate_branches", None)):
            try:
                branches = await _maybe_await(storage.get_debate_branches(debate_id))
                return json_response({"debate_id": debate_id, "branches": branches})
            except (KeyError, ValueError, OSError, TypeError, AttributeError) as e:
                logger.warning("Failed to get branches for %s from storage: %s", debate_id, e)

        branches = debate.get("branches")
        if isinstance(branches, list):
            return json_response({"debate_id": debate_id, "branches": branches})
        graph = debate.get("graph")
        if isinstance(graph, dict):
            graph_branches = graph.get("branches")
            if isinstance(graph_branches, dict):
                return json_response(
                    {"debate_id": debate_id, "branches": list(graph_branches.values())}
                )

        return error_response("Failed to retrieve branches", 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/debates/graph/{debate_id}/nodes",
        summary="Get graph debate nodes",
        description="Get all nodes in a graph-structured debate.",
        tags=["Debates", "Graph Debates"],
        parameters=[
            {"name": "debate_id", "in": "path", "required": True, "schema": {"type": "string"}}
        ],
        responses={
            "200": {"description": "List of debate nodes"},
            "401": {"description": "Authentication required"},
            "503": {"description": "Storage not configured"},
        },
    )
    async def _get_nodes(self, handler: Any, debate_id: str, scope: OrgScope) -> HandlerResult:
        """Get all nodes in a graph debate."""
        debate = await self._resolve_graph_debate(handler, debate_id, scope)
        if debate is None:
            return record_not_found("Graph debate")

        storage = getattr(handler, "storage", None)
        if storage and callable(getattr(storage, "get_debate_nodes", None)):
            try:
                nodes = await _maybe_await(storage.get_debate_nodes(debate_id))
                return json_response({"debate_id": debate_id, "nodes": nodes})
            except (KeyError, ValueError, OSError, TypeError, AttributeError) as e:
                logger.warning("Failed to get nodes for %s from storage: %s", debate_id, e)

        graph = debate.get("graph")
        if isinstance(graph, dict):
            graph_nodes = graph.get("nodes")
            if isinstance(graph_nodes, dict):
                return json_response({"debate_id": debate_id, "nodes": list(graph_nodes.values())})

        return error_response("Failed to retrieve nodes", 500)
