"""
Agent routing and team selection endpoint handlers.

Endpoints:
- GET /api/routing/best-teams - Get best-performing team combinations
- POST /api/routing/recommendations - Get agent recommendations for a task
- POST /api/routing/auto-route - Auto-route task with domain detection
- POST /api/routing/detect-domain - Detect domain from task text
- GET /api/routing/domain-leaderboard - Get agents ranked by domain
"""

from __future__ import annotations

__all__ = [
    "RoutingHandler",
]

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from aragora.utils.optional_imports import try_import

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    get_clamped_int_param,
    handle_errors,
    json_response,
)
from aragora.rbac.decorators import require_permission
from aragora.server.versioning.compat import strip_version_prefix
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter for routing endpoints (100 requests per minute - internal routing)
_routing_limiter = RateLimiter(requests_per_minute=100)

# Lazy imports for optional dependencies
_routing_imports, ROUTING_AVAILABLE = try_import(
    "aragora.routing.selection",
    "AgentSelector",
    "TaskRequirements",
    "DomainDetector",
    "DEFAULT_AGENT_EXPERTISE",
)
AgentSelector = _routing_imports.get("AgentSelector")
TaskRequirements = _routing_imports.get("TaskRequirements")
DomainDetector = _routing_imports.get("DomainDetector")
DEFAULT_AGENT_EXPERTISE = _routing_imports.get("DEFAULT_AGENT_EXPERTISE")


class RoutingHandler(BaseHandler):
    """Handler for agent routing endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/routing/best-teams",
        "/api/routing/recommendations",
        "/api/routing/auto-route",
        "/api/routing/detect-domain",
        "/api/routing/domain-leaderboard",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        return strip_version_prefix(path) in self.ROUTES

    @require_permission("routing:read")
    def handle(self, path: str, query_params: dict, handler: Any = None) -> HandlerResult | None:
        """Route GET requests to appropriate methods."""
        path = strip_version_prefix(path)
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _routing_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for routing endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        if path == "/api/routing/best-teams":
            min_debates = get_clamped_int_param(
                query_params, "min_debates", 3, min_val=1, max_val=20
            )
            limit = get_clamped_int_param(query_params, "limit", 10, min_val=1, max_val=50)
            return self._get_best_team_combinations(min_debates, limit)
        if path == "/api/routing/domain-leaderboard":
            domain = query_params.get("domain", ["general"])[0]
            limit = get_clamped_int_param(query_params, "limit", 10, min_val=1, max_val=50)
            return self._get_domain_leaderboard(domain, limit)
        return None

    @handle_errors("routing creation")
    @require_permission("routing:create")
    def handle_post(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route POST requests to appropriate methods."""
        path = strip_version_prefix(path)
        if path == "/api/routing/recommendations":
            return self._get_recommendations(handler)
        if path == "/api/routing/auto-route":
            return self._auto_route(handler)
        if path == "/api/routing/detect-domain":
            return self._detect_domain(handler)
        return None

    @handle_errors("best team combinations")
    def _get_best_team_combinations(self, min_debates: int, limit: int) -> HandlerResult:
        """Get best-performing team combinations from history."""
        if not ROUTING_AVAILABLE or not AgentSelector:
            return error_response("Agent selector not available", 503)

        elo_system = self.get_elo_system()
        persona_manager = self.ctx.get("persona_manager")

        selector = AgentSelector(
            elo_system=elo_system,
            persona_manager=persona_manager,
        )
        combinations = selector.get_best_team_combinations(min_debates=min_debates)[:limit]

        return json_response(
            {
                "min_debates": min_debates,
                "combinations": combinations,
                "count": len(combinations),
            }
        )

    @handle_errors("routing recommendations")
    def _get_recommendations(self, handler: Any) -> HandlerResult:
        """Get agent recommendations for a task.

        POST body:
            primary_domain: Primary domain for the task (default: 'general')
            secondary_domains: List of secondary domains
            required_traits: List of required agent traits
            task_id: Optional task identifier
            limit: Maximum recommendations to return (default: 5, max: 20)

        Returns:
            Ranked list of agent recommendations with scores.
        """
        if not ROUTING_AVAILABLE or not AgentSelector or not TaskRequirements:
            return error_response("Agent selector not available", 503)

        # Read request body
        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body or body too large", 400)

        primary_domain = body.get("primary_domain", "general")
        secondary_domains = body.get("secondary_domains", [])
        required_traits = body.get("required_traits", [])
        limit = min(body.get("limit", 5), 20)
        task_id = body.get("task_id", "ad-hoc")
        description = body.get("description", body.get("task", ""))

        requirements = TaskRequirements(
            task_id=task_id,
            description=description,
            primary_domain=primary_domain,
            secondary_domains=secondary_domains,
            required_traits=required_traits,
        )

        elo_system = self.get_elo_system()
        persona_manager = self.ctx.get("persona_manager")

        selector = AgentSelector(
            elo_system=elo_system,
            persona_manager=persona_manager,
        )
        recommendations = selector.get_recommendations(requirements, limit=limit)

        return json_response(
            {
                "task_id": task_id,
                "primary_domain": primary_domain,
                "recommendations": recommendations,
                "count": len(recommendations),
            }
        )

    @handle_errors("auto routing")
    def _auto_route(self, handler: Any) -> HandlerResult:
        """Auto-route a task with domain detection.

        POST body:
            task: Task description text (required)
            task_id: Optional task identifier
            exclude: Optional list of agents to exclude

        Returns:
            Team composition with detected domain and selected agents.
        """
        if not ROUTING_AVAILABLE or not AgentSelector or not DomainDetector:
            return error_response("Agent routing not available", 503)

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        task_text = body.get("task", "")
        if not task_text:
            return error_response("Missing 'task' field", 400)

        task_id = body.get("task_id")
        exclude = body.get("exclude", [])

        # Create selector with defaults
        elo_system = self.get_elo_system()
        selector = AgentSelector.create_with_defaults(elo_system=elo_system)

        # Auto-route
        team = selector.auto_route(task_text, task_id=task_id, exclude=exclude)

        return json_response(
            {
                "task_id": team.task_id,
                "detected_domain": team.agents[0].expertise if team.agents else {},
                "team": {
                    "agents": [a.name for a in team.agents],
                    "roles": team.roles,
                    "expected_quality": team.expected_quality,
                    "diversity_score": team.diversity_score,
                },
                "rationale": team.rationale,
            }
        )

    @handle_errors("domain detection")
    def _detect_domain(self, handler: Any) -> HandlerResult:
        """Detect domain from task text.

        POST body:
            task: Task description text (required)
            top_n: Number of domains to return (default: 3)

        Returns:
            Detected domains with confidence scores.
        """
        if not ROUTING_AVAILABLE or not DomainDetector:
            return error_response("Domain detection not available", 503)

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        task_text = body.get("task", "")
        if not task_text:
            return error_response("Missing 'task' field", 400)

        top_n = min(body.get("top_n", 3), 10)

        detector = DomainDetector()
        domains = detector.detect(task_text, top_n=top_n)

        return json_response(
            {
                "task": task_text[:200] + "..." if len(task_text) > 200 else task_text,
                "domains": [{"domain": d, "confidence": round(c, 3)} for d, c in domains],
                "primary_domain": domains[0][0] if domains else "general",
            }
        )

    @handle_errors("domain leaderboard")
    def _get_domain_leaderboard(self, domain: str, limit: int) -> HandlerResult:
        """Get agents ranked by domain expertise.

        Query params:
            domain: Domain to rank by (default: 'general')
            limit: Max agents to return (default: 10)

        Returns:
            Agents ranked by domain-specific scores.
        """
        if not ROUTING_AVAILABLE or not AgentSelector:
            return error_response("Agent routing not available", 503)

        elo_system = self.get_elo_system()
        selector = AgentSelector.create_with_defaults(elo_system=elo_system)

        leaderboard = selector.get_domain_leaderboard(domain, limit=limit)

        return json_response(
            {
                "domain": domain,
                "leaderboard": leaderboard,
                "count": len(leaderboard),
            }
        )
