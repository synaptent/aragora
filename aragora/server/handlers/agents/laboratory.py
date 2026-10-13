"""
Persona laboratory endpoint handlers.

Endpoints:
- GET /api/laboratory/emergent-traits - Get emergent traits from agent performance
- GET /api/laboratory/agent/{agent_name}/analysis - Get trait analysis for an agent
- POST /api/laboratory/cross-pollinations/suggest - Suggest beneficial trait transfers
"""

from __future__ import annotations

__all__ = [
    "LaboratoryHandler",
]

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from aragora.rbac.decorators import require_permission
from aragora.server.versioning.compat import strip_version_prefix
from aragora.utils.optional_imports import try_import

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    get_bounded_float_param,
    get_clamped_int_param,
    handle_errors,
    json_response,
)
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter for laboratory endpoints (20 requests per minute)
_laboratory_limiter = RateLimiter(requests_per_minute=20)

# Optional PersonaLaboratory import
_lab_imports, LABORATORY_AVAILABLE = try_import("aragora.agents.laboratory", "PersonaLaboratory")
PersonaLaboratory = _lab_imports.get("PersonaLaboratory")


class LaboratoryHandler(BaseHandler):
    """Handler for persona laboratory endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/v1/laboratory/emergent-traits",
        "/api/v1/laboratory/cross-pollinations",
        "/api/v1/laboratory/cross-pollinations/suggest",
        "/api/v1/laboratory/experiments",
    ]

    DYNAMIC_ROUTES = [
        "/api/v1/laboratory/agent/{agent_name}/analysis",
    ]

    _AGENT_ANALYSIS_PREFIX = "/api/laboratory/agent/"

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        normalized = strip_version_prefix(path)
        normalized_routes = {strip_version_prefix(route) for route in self.ROUTES}
        if normalized in normalized_routes:
            return True
        return normalized.startswith(self._AGENT_ANALYSIS_PREFIX) and normalized.endswith(
            "/analysis"
        )

    @require_permission("laboratory:read")
    def handle(self, path: str, query_params: dict, handler: Any = None) -> HandlerResult | None:
        """Route GET requests to appropriate methods."""
        path = strip_version_prefix(path)

        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _laboratory_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for laboratory endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        if path == "/api/laboratory/emergent-traits":
            min_confidence = get_bounded_float_param(
                query_params, "min_confidence", 0.5, min_val=0.0, max_val=1.0
            )
            limit = get_clamped_int_param(query_params, "limit", 20, min_val=1, max_val=100)
            return self._get_emergent_traits(min_confidence, limit)
        if path.startswith(self._AGENT_ANALYSIS_PREFIX) and path.endswith("/analysis"):
            # /api/laboratory/agent/{name}/analysis → segment 4
            agent_name, err = self.extract_path_param(path, 4, "agent_name")
            if err:
                return err
            return self._get_agent_analysis(agent_name)
        return None

    @handle_errors("laboratory creation")
    @require_permission("laboratory:create")
    def handle_post(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route POST requests to appropriate methods."""
        path = strip_version_prefix(path)

        # Rate limit check (shared with GET)
        client_ip = get_client_ip(handler)
        if not _laboratory_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for laboratory POST endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        if path == "/api/laboratory/cross-pollinations/suggest":
            return self._suggest_cross_pollinations(handler)
        return None

    @handle_errors("agent trait analysis")
    def _get_agent_analysis(self, agent_name: str) -> HandlerResult:
        """Get detailed trait analysis for a specific agent."""
        if not LABORATORY_AVAILABLE or not PersonaLaboratory:
            return error_response("Persona laboratory not available", 503)

        nomic_dir = self.get_nomic_dir()
        persona_manager = self.ctx.get("persona_manager")

        lab = PersonaLaboratory(
            db_path=str(nomic_dir / "laboratory.db") if nomic_dir else None,
            persona_manager=persona_manager,
        )

        traits = lab.detect_emergent_traits()
        agent_traits = [t for t in traits if t.agent_name == agent_name]

        return json_response(
            {
                "agent": agent_name,
                "traits": [
                    {
                        "trait": t.trait_name,
                        "domain": t.domain,
                        "confidence": t.confidence,
                        "evidence": t.evidence,
                        "detected_at": t.detected_at,
                    }
                    for t in agent_traits
                ],
                "count": len(agent_traits),
            }
        )

    @handle_errors("emergent traits")
    def _get_emergent_traits(self, min_confidence: float, limit: int) -> HandlerResult:
        """Get emergent traits detected from agent performance patterns.

        Query params:
            min_confidence: Minimum confidence threshold (0.0-1.0, default: 0.5)
            limit: Maximum traits to return (default: 20, max: 100)

        Returns:
            List of emergent traits with agent, domain, confidence, and evidence.
        """
        if not LABORATORY_AVAILABLE or not PersonaLaboratory:
            return error_response("Persona laboratory not available", 503)

        nomic_dir = self.get_nomic_dir()
        persona_manager = self.ctx.get("persona_manager")

        lab = PersonaLaboratory(
            db_path=str(nomic_dir / "laboratory.db") if nomic_dir else None,
            persona_manager=persona_manager,
        )
        traits = lab.detect_emergent_traits()

        # Filter by confidence and limit
        filtered = [t for t in traits if t.confidence >= min_confidence][:limit]

        return json_response(
            {
                "emergent_traits": [
                    {
                        "agent": t.agent_name,
                        "trait": t.trait_name,
                        "domain": t.domain,
                        "confidence": t.confidence,
                        "evidence": t.evidence,
                        "detected_at": t.detected_at,
                    }
                    for t in filtered
                ],
                "count": len(filtered),
                "min_confidence": min_confidence,
            }
        )

    @handle_errors("cross pollinations")
    def _suggest_cross_pollinations(self, handler: Any) -> HandlerResult:
        """Suggest beneficial trait transfers for a target agent.

        POST body:
            target_agent: The agent to suggest traits for (required)

        Returns:
            List of suggested trait transfers with source, trait, and reason.
        """
        if not LABORATORY_AVAILABLE or not PersonaLaboratory:
            return error_response("Persona laboratory not available", 503)

        # Read request body
        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body or body too large", 400)

        target_agent = body.get("target_agent")
        if not target_agent:
            return error_response("target_agent required", 400)

        nomic_dir = self.get_nomic_dir()
        persona_manager = self.ctx.get("persona_manager")

        lab = PersonaLaboratory(
            db_path=str(nomic_dir / "laboratory.db") if nomic_dir else None,
            persona_manager=persona_manager,
        )
        suggestions = lab.suggest_cross_pollinations(target_agent)

        return json_response(
            {
                "target_agent": target_agent,
                "suggestions": [
                    {
                        "source_agent": s[0],
                        "trait_or_domain": s[1],
                        "reason": s[2],
                    }
                    for s in suggestions
                ],
                "count": len(suggestions),
            }
        )
