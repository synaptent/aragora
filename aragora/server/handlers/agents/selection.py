"""
Selection Plugin API Handlers.

Exposes the selection plugin architecture via REST API:
- List available plugins (scorers, team selectors, role assigners)
- Score agents for a task
- Select optimal teams
- Get plugin details

Routes:
- GET  /api/selection/plugins               List all available plugins
- GET  /api/selection/defaults              Get default plugin configuration
- GET  /api/selection/scorers/<name>        Get scorer details
- GET  /api/selection/team-selectors/<name> Get team selector details
- GET  /api/selection/role-assigners/<name> Get role assigner details
- POST /api/selection/score                 Score agents for a task
- POST /api/selection/team                  Select a team for a task
"""

from __future__ import annotations

__all__ = [
    "SelectionHandler",
]

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from aragora.plugins.selection import (
    SelectionContext,
    get_selection_registry,
)
from aragora.routing.selection import (
    AgentProfile,
    DEFAULT_AGENT_EXPERTISE,
    DomainDetector,
    TaskRequirements,
)
from aragora.routing.team_builder import TeamBuilder

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from aragora.rbac.decorators import require_permission
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter for selection endpoints (100 requests per minute)
_selection_limiter = RateLimiter(requests_per_minute=100)

# Global team builder for selection history tracking
_team_builder: TeamBuilder | None = None


def get_team_builder() -> TeamBuilder:
    """Get or create the global TeamBuilder instance."""
    global _team_builder
    if _team_builder is None:
        _team_builder = TeamBuilder()
    return _team_builder


def _create_agent_pool() -> dict[str, AgentProfile]:
    """Create a pool of agents with default expertise profiles."""
    pool = {}
    for agent_name, expertise in DEFAULT_AGENT_EXPERTISE.items():
        profile = AgentProfile(
            name=agent_name,
            agent_type=agent_name,
            expertise=expertise.copy(),
        )
        pool[agent_name] = profile
    return pool


class SelectionHandler(BaseHandler):
    """Handler for selection plugin endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/v1/selection/plugins",
        "/api/v1/selection/defaults",
        "/api/v1/selection/scorers",
        "/api/v1/selection/team-selectors",
        "/api/v1/selection/role-assigners",
        "/api/v1/selection/score",
        "/api/v1/selection/team",
        "/api/v1/team-selection",
        # SDK agent-selection aliases
        "/api/v1/agent-selection/plugins",
        "/api/v1/agent-selection/defaults",
        "/api/v1/agent-selection/score",
        "/api/v1/agent-selection/best",
        "/api/v1/agent-selection/select-team",
        "/api/v1/agent-selection/assign-roles",
        "/api/v1/agent-selection/history",
    ]

    # Routes with path parameters
    PREFIX_ROUTES = [
        "/api/v1/selection/scorers/",
        "/api/v1/selection/team-selectors/",
        "/api/v1/selection/role-assigners/",
    ]

    def _normalize_path(self, path: str) -> str:
        """Normalize agent-selection paths to selection paths."""
        return path.replace("/agent-selection/", "/selection/")

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        if path in self.ROUTES:
            return True
        return any(path.startswith(prefix) for prefix in self.PREFIX_ROUTES)

    @require_permission("selection:read")
    def handle(self, path: str, query_params: dict, handler: Any = None) -> HandlerResult | None:
        """Route GET requests to appropriate methods."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _selection_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for selection endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        # Normalize agent-selection alias paths
        path = self._normalize_path(path)

        if path == "/api/v1/selection/plugins":
            return self._list_plugins()
        if path == "/api/v1/selection/defaults":
            return self._get_defaults()
        if path == "/api/v1/selection/scorers":
            return self._list_scorers()
        if path == "/api/v1/selection/team-selectors":
            return self._list_team_selectors()
        if path == "/api/v1/selection/role-assigners":
            return self._list_role_assigners()
        if path == "/api/v1/selection/history":
            return self._get_history(query_params)
        if path.startswith("/api/v1/selection/scorers/"):
            name = path.split("/")[-1]
            return self._get_scorer(name)
        if path.startswith("/api/v1/selection/team-selectors/"):
            name = path.split("/")[-1]
            return self._get_team_selector(name)
        if path.startswith("/api/v1/selection/role-assigners/"):
            name = path.split("/")[-1]
            return self._get_role_assigner(name)
        return None

    @handle_errors("selection creation")
    @require_permission("selection:create")
    def handle_post(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route POST requests to appropriate methods."""
        # Normalize agent-selection alias paths
        path = self._normalize_path(path)

        if path in ("/api/v1/selection/score", "/api/v1/selection/best"):
            return self._score_agents(handler)
        if path in (
            "/api/v1/selection/team",
            "/api/v1/team-selection",
            "/api/v1/selection/select-team",
        ):
            return self._select_team(handler)
        if path == "/api/v1/selection/assign-roles":
            return self._assign_roles(handler)
        return None

    @handle_errors("list plugins")
    def _list_plugins(self) -> HandlerResult:
        """List all available selection plugins."""
        plugin_registry = get_selection_registry()
        return json_response(plugin_registry.list_all_plugins())

    @handle_errors("get defaults")
    def _get_defaults(self) -> HandlerResult:
        """Get default plugin configuration."""
        plugin_registry = get_selection_registry()
        return json_response(
            {
                "scorer": plugin_registry._default_scorer,
                "team_selector": plugin_registry._default_team_selector,
                "role_assigner": plugin_registry._default_role_assigner,
            }
        )

    @handle_errors("list scorers")
    def _list_scorers(self) -> HandlerResult:
        """List available scorer plugins."""
        plugin_registry = get_selection_registry()
        scorers = [plugin_registry.get_scorer_info(name) for name in plugin_registry.list_scorers()]
        return json_response({"scorers": scorers})

    @handle_errors("list team selectors")
    def _list_team_selectors(self) -> HandlerResult:
        """List available team selector plugins."""
        plugin_registry = get_selection_registry()
        selectors = [
            plugin_registry.get_team_selector_info(name)
            for name in plugin_registry.list_team_selectors()
        ]
        return json_response({"team_selectors": selectors})

    @handle_errors("list role assigners")
    def _list_role_assigners(self) -> HandlerResult:
        """List available role assigner plugins."""
        plugin_registry = get_selection_registry()
        assigners = [
            plugin_registry.get_role_assigner_info(name)
            for name in plugin_registry.list_role_assigners()
        ]
        return json_response({"role_assigners": assigners})

    @handle_errors("get scorer")
    def _get_scorer(self, name: str) -> HandlerResult:
        """Get information about a specific scorer."""
        plugin_registry = get_selection_registry()
        try:
            info = plugin_registry.get_scorer_info(name)
            return json_response(info)
        except KeyError:
            return error_response(
                f"Unknown scorer: {name}. Available: {plugin_registry.list_scorers()}",
                404,
            )

    @handle_errors("get team selector")
    def _get_team_selector(self, name: str) -> HandlerResult:
        """Get information about a specific team selector."""
        plugin_registry = get_selection_registry()
        try:
            info = plugin_registry.get_team_selector_info(name)
            return json_response(info)
        except KeyError:
            return error_response(
                f"Unknown team selector: {name}. Available: {plugin_registry.list_team_selectors()}",
                404,
            )

    @handle_errors("get role assigner")
    def _get_role_assigner(self, name: str) -> HandlerResult:
        """Get information about a specific role assigner."""
        plugin_registry = get_selection_registry()
        try:
            info = plugin_registry.get_role_assigner_info(name)
            return json_response(info)
        except KeyError:
            return error_response(
                f"Unknown role assigner: {name}. Available: {plugin_registry.list_role_assigners()}",
                404,
            )

    @handle_errors("score agents")
    def _score_agents(self, handler: Any) -> HandlerResult:
        """Score agents for a task."""
        try:
            body = self._get_json_body(handler)
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug("Invalid JSON in score_agents request: %s: %s", type(e).__name__, e)
            return error_response("Invalid JSON body", 400)
        except (AttributeError, TypeError, OSError) as e:
            logger.warning(
                "Unexpected error parsing score_agents request: %s: %s", type(e).__name__, e
            )
            return error_response("Invalid JSON body", 400)

        task_description = body.get("task_description")
        if not task_description:
            return error_response("task_description is required", 400)

        # Get scorer
        plugin_registry = get_selection_registry()
        scorer_name = body.get("scorer")
        try:
            scorer = plugin_registry.get_scorer(scorer_name)
        except KeyError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request", 400)

        # Detect or use provided domains
        detector = DomainDetector()
        primary_domain = body.get("primary_domain")
        if not primary_domain:
            primary_domain = detector.get_primary_domain(task_description)

        secondary_domains = body.get("secondary_domains", [])
        required_traits = body.get("required_traits", [])

        # Create requirements
        requirements = TaskRequirements(
            task_id=f"score-{hash(task_description) % 10000:04d}",
            description=task_description[:500],
            primary_domain=primary_domain,
            secondary_domains=secondary_domains,
            required_traits=required_traits,
        )

        # Create context
        agent_pool = _create_agent_pool()
        context = SelectionContext(agent_pool=agent_pool)

        # Score all agents
        scored_agents: list[dict[str, str | float]] = []
        for agent in agent_pool.values():
            score = scorer.score_agent(agent, requirements, context)
            scored_agents.append(
                {
                    "name": agent.name,
                    "type": agent.agent_type,
                    "score": round(score, 4),
                    "domain_expertise": agent.expertise.get(primary_domain, 0.5),
                    "elo_rating": agent.elo_rating,
                }
            )

        # Sort by score (score is always a float in this list)
        scored_agents.sort(key=lambda x: float(x["score"]), reverse=True)

        return json_response(
            {
                "scorer_used": scorer.name,
                "agents": scored_agents,
                "task_id": requirements.task_id,
            }
        )

    @handle_errors("select team")
    def _select_team(self, handler: Any) -> HandlerResult:
        """Select an optimal team for a task."""
        try:
            body = self._get_json_body(handler)
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug("Invalid JSON in select_team request: %s: %s", type(e).__name__, e)
            return error_response("Invalid JSON body", 400)
        except (AttributeError, TypeError, OSError) as e:
            logger.warning(
                "Unexpected error parsing select_team request: %s: %s", type(e).__name__, e
            )
            return error_response("Invalid JSON body", 400)

        task_description = body.get("task_description")
        if not task_description:
            return error_response("task_description is required", 400)

        # Get plugins
        plugin_registry = get_selection_registry()
        try:
            scorer = plugin_registry.get_scorer(body.get("scorer"))
            team_selector = plugin_registry.get_team_selector(body.get("team_selector"))
            role_assigner = plugin_registry.get_role_assigner(body.get("role_assigner"))
        except KeyError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request", 400)

        # Detect or use provided domains
        detector = DomainDetector()
        primary_domain = body.get("primary_domain")
        if not primary_domain:
            primary_domain = detector.get_primary_domain(task_description)

        # Create requirements
        requirements = TaskRequirements(
            task_id=f"team-{hash(task_description) % 10000:04d}",
            description=task_description[:500],
            primary_domain=primary_domain,
            secondary_domains=body.get("secondary_domains", []),
            required_traits=body.get("required_traits", []),
            min_agents=body.get("min_agents", 2),
            max_agents=body.get("max_agents", 5),
            quality_priority=body.get("quality_priority", 0.5),
            diversity_preference=body.get("diversity_preference", 0.5),
        )

        # Create context
        agent_pool = _create_agent_pool()
        exclude = body.get("exclude_agents", [])
        for name in exclude:
            agent_pool.pop(name, None)

        context = SelectionContext(agent_pool=agent_pool)

        # Score agents
        scored_agents = []
        for agent in agent_pool.values():
            score = scorer.score_agent(agent, requirements, context)
            scored_agents.append((agent, score))
        scored_agents.sort(key=lambda x: x[1], reverse=True)

        # Select team
        team = team_selector.select_team(scored_agents, requirements, context)

        # Assign roles
        roles = role_assigner.assign_roles(team, requirements, context)

        # Build response
        team_members: list[dict[str, Any]] = []
        for agent in team:
            team_members.append(
                {
                    "name": agent.name,
                    "type": agent.agent_type,
                    "role": roles.get(agent.name, "participant"),
                    "score": next((s for a, s in scored_agents if a.name == agent.name), 0),
                    "expertise": agent.expertise,
                    "elo_rating": agent.elo_rating,
                }
            )

        # Calculate metrics
        expected_quality = (
            sum(float(m["score"]) for m in team_members) / len(team_members)
            if team_members
            else 0.0
        )
        expected_cost = sum(a.cost_factor for a in team)

        # Diversity score
        types = set(a.agent_type for a in team)
        diversity_score = len(types) / len(team) if team else 0

        # Generate rationale
        rationale = (
            f"Selected {len(team)} agents for '{primary_domain}' task. "
            f"Team includes: {', '.join(a.name for a in team)}. "
            f"Diversity: {diversity_score:.0%}, Quality: {expected_quality:.0%}"
        )

        return json_response(
            {
                "team_id": f"team-{requirements.task_id}",
                "task_id": requirements.task_id,
                "agents": team_members,
                "expected_quality": round(expected_quality, 4),
                "expected_cost": round(expected_cost, 2),
                "diversity_score": round(diversity_score, 4),
                "rationale": rationale,
                "plugins_used": {
                    "scorer": scorer.name,
                    "team_selector": team_selector.name,
                    "role_assigner": role_assigner.name,
                },
            }
        )

    @handle_errors("get selection history")
    def _get_history(self, query_params: dict) -> HandlerResult:
        """Get agent selection history."""
        limit = max(1, min(int(query_params.get("limit", 20)), 500))
        offset = max(0, int(query_params.get("offset", 0)))

        team_builder = get_team_builder()
        # Get all history then apply offset/limit for pagination
        all_history = team_builder.get_selection_history()
        total = len(all_history)

        # Apply pagination
        paginated = all_history[offset : offset + limit]

        return json_response(
            {
                "selections": paginated,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )

    @handle_errors("assign roles")
    def _assign_roles(self, handler: Any) -> HandlerResult:
        """Assign roles to a list of agents for a task."""
        try:
            body = self._get_json_body(handler)
        except (json.JSONDecodeError, ValueError):
            return error_response("Invalid JSON body", 400)

        agent_names = body.get("agents", [])
        task_description = body.get("task_description")
        if not task_description or not agent_names:
            return error_response("task_description and agents are required", 400)

        plugin_registry = get_selection_registry()
        try:
            role_assigner = plugin_registry.get_role_assigner(body.get("role_assigner"))
        except KeyError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request", 400)

        agent_pool = _create_agent_pool()
        agents = [agent_pool[n] for n in agent_names if n in agent_pool]
        if not agents:
            return error_response("No valid agents found", 400)

        detector = DomainDetector()
        primary_domain = body.get("primary_domain") or detector.get_primary_domain(task_description)

        requirements = TaskRequirements(
            task_id=f"roles-{hash(task_description) % 10000:04d}",
            description=task_description[:500],
            primary_domain=primary_domain,
        )
        context = SelectionContext(agent_pool=agent_pool)
        roles = role_assigner.assign_roles(agents, requirements, context)

        return json_response(
            {
                "task_id": requirements.task_id,
                "assignments": [{"agent": name, "role": role} for name, role in roles.items()],
                "role_assigner": role_assigner.name,
            }
        )

    def _get_json_body(self, handler: Any) -> dict[str, Any]:
        """Extract JSON body from request handler."""
        if hasattr(handler, "request_body"):
            import json

            return json.loads(handler.request_body.decode("utf-8"))
        return {}
