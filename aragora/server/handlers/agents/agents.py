"""
Agent-related endpoint handlers.

Endpoints:
- GET /api/leaderboard - Get agent rankings
- GET /api/rankings - Get agent rankings (alias)
- GET /api/agents/local - List detected local LLM servers
- GET /api/agents/local/status - Get local LLM availability status
- GET /api/agent/{name}/profile - Get agent profile
- GET /api/agent/{name}/history - Get agent match history
- GET /api/agent/{name}/calibration - Get calibration scores
- GET /api/agent/{name}/consistency - Get consistency score
- GET /api/agent/{name}/flips - Get agent flip history
- GET /api/agent/{name}/network - Get relationship network
- GET /api/agent/{name}/rivals - Get top rivals
- GET /api/agent/{name}/allies - Get top allies
- GET /api/agent/{name}/moments - Get significant moments
- GET /api/agent/{name}/positions - Get position history
- GET /api/agent/{name}/metadata - Get agent metadata (model, capabilities)
- GET /api/agent/compare - Compare multiple agents
- GET /api/agent/{name}/head-to-head/{opponent} - Get head-to-head stats
- GET /api/flips/recent - Get recent flips across all agents
- GET /api/flips/summary - Get flip summary for dashboard

View endpoints are in agent_rankings.py (AgentRankingsMixin).
Profile endpoints are in agent_profiles.py (AgentProfilesMixin).
Intelligence endpoints are in agent_intelligence.py (AgentIntelligenceMixin).
Flip endpoints are in agent_flips.py (AgentFlipsMixin).
"""

from __future__ import annotations

import logging
import os
import re

from aragora.events.handler_events import emit_handler_event, QUERIED
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.protocols import HTTPRequestHandler
    from aragora.rbac.decorators import require_permission  # noqa: F401

from aragora.config import (
    CACHE_TTL_LEADERBOARD,
)
from aragora.config.model_pins import (
    FABLE_51_VIA_OPENROUTER,
    GEMINI_38_FLASH_VIA_OPENROUTER,
    GPT6_ASTRA_VIA_OPENROUTER,
    GROK_46_VIA_OPENROUTER,
    MISTRAL_MEDIUM_VIA_OPENROUTER,
)

logger = logging.getLogger(__name__)
from aragora.server.versioning.compat import strip_version_prefix

from ..base import (
    SAFE_AGENT_PATTERN,
    SAFE_ID_PATTERN,
    HandlerResult,
    agent_to_dict,
    error_response,
    get_int_param,
    get_string_param,
    handle_errors,
    json_response,
    ttl_cache,
    validate_path_segment,
)
from ..openapi_decorator import api_endpoint
from ..secure import ForbiddenError, SecureHandler, UnauthorizedError
from ..utils.rate_limit import RateLimiter, get_client_ip, rate_limit

# Import mixin classes
from .agent_rankings import AgentRankingsMixin
from .agent_profiles import AgentProfilesMixin
from .agent_intelligence import AgentIntelligenceMixin
from .agent_flips import AgentFlipsMixin

# RBAC permissions for agent endpoints
AGENTS_READ_PERMISSION = "agents:read"
AGENTS_WRITE_PERMISSION = "agents:write"

# Legacy alias for compatibility
AGENT_PERMISSION = AGENTS_READ_PERMISSION

# Rate limiter for agent handlers (60 requests per minute)
_agent_limiter = RateLimiter(requests_per_minute=60)

_ENV_VAR_RE = re.compile(r"[A-Z][A-Z0-9_]+")
# Per-provider OpenRouter fallback targets, derived from aragora.config.
# model_pins (frontier-model-refresh, 2026-09-04). The previous hand-written
# slugs had drifted to retired/nonexistent spellings (openai/gpt-4.1-mini,
# google/gemini-3-flash-preview, x-ai/grok-4.5).
_OPENROUTER_FALLBACK_MODELS = {
    "anthropic-api": FABLE_51_VIA_OPENROUTER,
    "openai-api": GPT6_ASTRA_VIA_OPENROUTER,
    "gemini": GEMINI_38_FLASH_VIA_OPENROUTER,
    "grok": GROK_46_VIA_OPENROUTER,
    "mistral-api": MISTRAL_MEDIUM_VIA_OPENROUTER,
}


def _secret_configured(name: str) -> bool:
    try:
        from aragora.config.secrets import get_secret

        value = get_secret(name)
        if value and value.strip():
            return True
    except (ImportError, KeyError, ValueError, OSError) as e:
        # Secrets module may not be available, fall back to env vars
        logger.debug("Could not get secret '%s': %s", name, e)
    env_value = os.getenv(name)
    return bool(env_value and env_value.strip())


def _missing_required_env_vars(env_vars: str | None) -> list[str]:
    if not env_vars:
        return []
    if "optional" in env_vars.lower():
        return []
    candidates = _ENV_VAR_RE.findall(env_vars)
    if not candidates:
        return []
    if any(_secret_configured(var) for var in candidates):
        return []
    return candidates


class AgentsHandler(  # type: ignore[misc]
    AgentRankingsMixin,
    AgentProfilesMixin,
    AgentIntelligenceMixin,
    AgentFlipsMixin,
    SecureHandler,
):
    """Handler for agent-related endpoints.

    Requires authentication and agent:read permission (RBAC).
    """

    def __init__(self, ctx: dict | None = None, server_context: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = server_context or ctx or {}

    ROUTES = [
        "/api/agents",
        "/api/agents/health",
        "/api/agents/availability",
        "/api/agents/local",
        "/api/agents/local/status",
        "/api/leaderboard",
        "/api/rankings",
        # Note: /api/calibration/leaderboard handled by CalibrationHandler
        "/api/matches/recent",
        "/api/agent/compare",
        "/api/agent/*/profile",
        "/api/agent/*/history",
        "/api/agent/*/calibration",
        "/api/agent/*/consistency",
        "/api/agent/*/flips",
        "/api/agent/*/network",
        "/api/agent/*/rivals",
        "/api/agent/*/allies",
        "/api/agent/*/moments",
        "/api/agent/*/positions",
        "/api/agent/*/domains",
        "/api/agent/*/performance",
        "/api/agent/*/metadata",
        "/api/agent/*/head-to-head/*",
        "/api/agent/*/opponent-briefing/*",
        "/api/agent/*/introspect",
        "/api/flips/recent",
        "/api/flips/summary",
        "/api/v1/leaderboard/compare",
        "/api/v1/leaderboard/domains",
        "/api/v1/leaderboard/movers",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        path = strip_version_prefix(path)
        if path == "/api/agents":
            return True
        if path == "/api/agents/health":
            return True
        if path == "/api/agents/availability":
            return True
        if path in ("/api/agents/local", "/api/agents/local/status"):
            return True
        if path in ("/api/leaderboard", "/api/rankings"):
            return True
        if path == "/api/matches/recent":
            return True
        if path.startswith("/api/agents/") and not path.startswith(
            (
                "/api/agents/health",
                "/api/agents/availability",
                "/api/agents/local",
                "/api/agents/configs",
            )
        ):
            return True
        if path == "/api/agent/compare":
            return True
        if path.startswith("/api/agent/"):
            return True
        if path.startswith("/api/flips/"):
            return True
        return False

    # Public read-only paths (no auth required for GET)
    _PUBLIC_PATHS: frozenset[str] = frozenset(
        {
            "/api/agents",
            "/api/agents/health",
            "/api/agents/availability",
            "/api/leaderboard",
            "/api/rankings",
            "/api/flips/recent",
            "/api/flips/summary",
            "/api/matches/recent",
        }
    )

    # Public prefixes (no auth required for GET)
    _PUBLIC_PREFIXES: tuple[str, ...] = ("/api/agent/",)

    def _is_public_path(self, path: str) -> bool:
        """Check if this is a public read-only path."""
        if path in self._PUBLIC_PATHS:
            return True
        return any(path.startswith(p) for p in self._PUBLIC_PREFIXES)

    async def handle(
        self, path: str, query_params: dict[str, Any], handler: HTTPRequestHandler
    ) -> HandlerResult | None:
        """Route agent requests with RBAC."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _agent_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for agent endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        normalized_path = strip_version_prefix(path)
        is_public = self._is_public_path(normalized_path)

        # RBAC: Skip auth for public read-only endpoints, require for mutations
        if not is_public:
            try:
                auth_context = await self.get_auth_context(handler, require_auth=True)
                self.check_permission(auth_context, AGENT_PERMISSION)
            except UnauthorizedError:
                return error_response("Authentication required to access agent data", 401)
            except ForbiddenError as e:
                logger.warning("Agent access denied: %s", e)
                return error_response("Permission denied", 403)

        path = strip_version_prefix(path)
        if path.startswith("/api/agents/") and not path.startswith(
            (
                "/api/agents/health",
                "/api/agents/availability",
                "/api/agents/local",
                "/api/agents/configs",
            )
        ):
            path = path.replace("/api/agents/", "/api/agent/", 1)
        # Agent health endpoint (must come before /api/agents check)
        if path == "/api/agents/health":
            return self._get_agent_health()

        if path == "/api/agents/availability":
            return self._get_agent_availability()

        # Local LLM endpoints (must come before /api/agents check)
        if path == "/api/agents/local":
            return self._list_local_agents()

        if path == "/api/agents/local/status":
            return self._get_local_status()

        # List all agents
        if path == "/api/agents":
            include_stats = (
                get_string_param(query_params, "include_stats", "false").lower() == "true"
            )
            return self._list_agents(include_stats)

        # Leaderboard endpoints
        if path in ("/api/leaderboard", "/api/rankings"):
            limit = get_int_param(query_params, "limit", 20)
            domain = get_string_param(query_params, "domain")
            if domain:
                is_valid, err = validate_path_segment(domain, "domain", SAFE_ID_PATTERN)
                if not is_valid:
                    return error_response(err, 400)
            return self._get_leaderboard(limit, domain)

        # Note: /api/calibration/leaderboard now handled by CalibrationHandler

        if path == "/api/matches/recent":
            limit = get_int_param(query_params, "limit", 10)
            loop_id = get_string_param(query_params, "loop_id")
            if loop_id:
                is_valid, err = validate_path_segment(loop_id, "loop_id", SAFE_ID_PATTERN)
                if not is_valid:
                    return error_response(err, 400)
            return self._get_recent_matches(limit, loop_id)

        # Agent comparison
        if path == "/api/agent/compare":
            agents = query_params.get("agents", [])
            if isinstance(agents, str):
                agents = [agents]
            return self._compare_agents(agents)

        # Per-agent endpoints
        if path.startswith("/api/agent/"):
            return self._handle_agent_endpoint(path, query_params)

        # Flip endpoints (not per-agent)
        if path == "/api/flips/recent":
            limit = get_int_param(query_params, "limit", 20)
            return self._get_recent_flips(limit)

        if path == "/api/flips/summary":
            return self._get_flip_summary()

        return None

    def _handle_agent_endpoint(self, path: str, query_params: dict) -> HandlerResult | None:
        """Handle /api/agent/{name}/* endpoints."""
        path = strip_version_prefix(path)
        parts = path.split("/")
        # Parts: ["", "api", "agent", "{name}", ...]
        if len(parts) < 5:
            return error_response("Invalid agent path", 400)

        # Extract and validate agent name (index 3 for versionless path)
        agent_name, err = self.extract_path_param(path, 3, "agent", SAFE_AGENT_PATTERN)
        if err:
            return err

        # Head-to-head: /api/agent/{name}/head-to-head/{opponent}
        # Parts: ["", "api", "agent", "{name}", "head-to-head", "{opponent}"]
        if len(parts) >= 6 and parts[4] == "head-to-head":
            opponent, err = self.extract_path_param(path, 5, "opponent", SAFE_AGENT_PATTERN)
            if err:
                return err
            return self._get_head_to_head(agent_name, opponent)

        # Opponent briefing: /api/agent/{name}/opponent-briefing/{opponent}
        if len(parts) >= 6 and parts[4] == "opponent-briefing":
            opponent, err = self.extract_path_param(path, 5, "opponent", SAFE_AGENT_PATTERN)
            if err:
                return err
            return self._get_opponent_briefing(agent_name, opponent)

        # Other endpoints: /api/agent/{name}/{endpoint}
        if len(parts) >= 5:
            endpoint = parts[4]
            return self._dispatch_agent_endpoint(agent_name, endpoint, query_params)

        return None

    def _dispatch_agent_endpoint(
        self, agent: str, endpoint: str, params: dict
    ) -> HandlerResult | None:
        """Dispatch to specific agent endpoint handler."""
        handlers = {
            "profile": lambda: self._get_profile(agent),
            "history": lambda: self._get_history(agent, get_int_param(params, "limit", 30)),
            "calibration": lambda: self._get_calibration(agent, params.get("domain")),
            "consistency": lambda: self._get_consistency(agent),
            "flips": lambda: self._get_agent_flips(agent, get_int_param(params, "limit", 20)),
            "network": lambda: self._get_network(agent),
            "rivals": lambda: self._get_rivals(agent, get_int_param(params, "limit", 5)),
            "allies": lambda: self._get_allies(agent, get_int_param(params, "limit", 5)),
            "moments": lambda: self._get_moments(agent, get_int_param(params, "limit", 10)),
            "positions": lambda: self._get_positions(agent, get_int_param(params, "limit", 20)),
            "domains": lambda: self._get_domains(agent),
            "performance": lambda: self._get_performance(agent),
            "metadata": lambda: self._get_metadata(agent),
            "introspect": lambda: self._get_agent_introspect(agent, params.get("debate_id")),
        }

        if endpoint in handlers:
            return handlers[endpoint]()

        return None

    # ------------------------------------------------------------------
    # Core agent methods (kept in main handler)
    # ------------------------------------------------------------------

    @api_endpoint(
        method="GET",
        path="/api/v1/agents",
        summary="List all known agents",
        tags=["Agents"],
    )
    @rate_limit(requests_per_minute=30, limiter_name="agents_list")
    @handle_errors("list agents")
    @ttl_cache(ttl_seconds=CACHE_TTL_LEADERBOARD, key_prefix="agents_list")
    def _list_agents(self, include_stats: bool = False) -> HandlerResult:
        """List all known agents.

        Args:
            include_stats: If True, include basic stats (ELO, match count)

        Returns:
            List of agent names or agent objects with stats
        """
        elo = self.get_elo_system()
        calibration_tracker = self.get_calibration_tracker() if include_stats else None
        agents = []

        # Get agents from ELO system if available
        if elo:
            try:
                # Get all agents from leaderboard (large limit to get all)
                rankings = elo.get_leaderboard(limit=500)
                for agent in rankings:
                    agent_dict = agent_to_dict(agent, calibration_tracker=calibration_tracker)
                    name = agent_dict.get("name", "")
                    if include_stats:
                        entry: dict[str, Any] = {
                            "name": name,
                            "elo": agent_dict.get("elo", 1500),
                            "matches": agent_dict.get("matches", 0),
                            "wins": agent_dict.get("wins", 0),
                            "losses": agent_dict.get("losses", 0),
                        }
                        if "calibration" in agent_dict:
                            entry["calibration"] = agent_dict["calibration"]
                        agents.append(entry)
                    else:
                        agents.append({"name": name})
            except (KeyError, ValueError, OSError, TypeError, AttributeError) as e:
                logger.warning("Could not get agents from ELO: %s", e)

        # Fallback to known agent types if no ELO data
        if not agents:
            from aragora.config import ALLOWED_AGENT_TYPES

            agents = [{"name": name} for name in ALLOWED_AGENT_TYPES]

        emit_handler_event("agent", QUERIED, {"total": len(agents)})
        return json_response(
            {
                "agents": agents,
                "total": len(agents),
            }
        )

    @api_endpoint(
        method="GET",
        path="/api/v1/agents/local",
        summary="List detected local LLM servers",
        tags=["Agents"],
    )
    @rate_limit(requests_per_minute=10, limiter_name="local_agents")
    @handle_errors("list local agents")
    def _list_local_agents(self) -> HandlerResult:
        """List detected local LLM servers (Ollama, LM Studio, etc.).

        Returns:
            List of detected local LLM servers with their available models
        """
        try:
            from aragora.agents.registry import AgentRegistry

            local_agents = AgentRegistry.detect_local_agents()

            return json_response(
                {
                    "servers": local_agents,
                    "total": len(local_agents),
                    "available_count": sum(1 for a in local_agents if a.get("available", False)),
                }
            )
        except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
            logger.warning("Could not detect local LLMs: %s", e)
            return json_response(
                {
                    "servers": [],
                    "total": 0,
                    "available_count": 0,
                    "error": "Internal server error",
                }
            )

    @api_endpoint(
        method="GET",
        path="/api/v1/agents/local/status",
        summary="Get local LLM availability status",
        tags=["Agents"],
    )
    @rate_limit(requests_per_minute=10, limiter_name="local_status")
    @handle_errors("get local status")
    def _get_local_status(self) -> HandlerResult:
        """Get overall local LLM availability status with recommendations.

        Returns:
            Status including availability, recommended server/model
        """
        try:
            from aragora.agents.registry import AgentRegistry

            status = AgentRegistry.get_local_status()

            return json_response(
                {
                    "available": status.get("any_available", False),
                    "total_models": status.get("total_models", 0),
                    "recommended": {
                        "server": status.get("recommended_server"),
                        "model": status.get("recommended_model"),
                    },
                    "available_agents": status.get("available_agents", []),
                    "servers": status.get("servers", []),
                }
            )
        except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
            logger.warning("Could not get local LLM status: %s", e)
            return json_response(
                {
                    "available": False,
                    "total_models": 0,
                    "recommended": {"server": None, "model": None},
                    "available_agents": [],
                    "servers": [],
                    "error": "Internal server error",
                }
            )

    @api_endpoint(
        method="GET",
        path="/api/v1/agents/health",
        summary="Get runtime health status for all agents",
        tags=["Agents"],
    )
    @rate_limit(requests_per_minute=30, limiter_name="agent_health")
    @handle_errors("get agent health")
    def _get_agent_health(self) -> HandlerResult:
        """Get runtime health status for all agents.

        Returns agent availability based on circuit breaker states,
        fallback chain status, and recent error metrics.

        Returns:
            Dict with health status for each agent type and overall system health
        """
        import time

        health: dict[str, Any] = {
            "timestamp": time.time(),
            "overall_status": "healthy",
            "agents": {},
            "circuit_breakers": {},
            "fallback": {},
        }

        # Get circuit breaker status
        try:
            from aragora.resilience import get_circuit_breakers

            circuit_breakers = get_circuit_breakers()
            if circuit_breakers:
                # Get all tracked agents from circuit breakers
                states = {
                    name: cb.get_status_dict() if hasattr(cb, "get_status_dict") else {}
                    for name, cb in circuit_breakers.items()
                }
                for agent_name, state in states.items():
                    health["circuit_breakers"][agent_name] = {
                        "state": state.get("state", "unknown"),
                        "failure_count": state.get("failure_count", 0),
                        "last_failure": state.get("last_failure_time"),
                        "available": state.get("state") != "open",
                    }

                    # Mark overall as degraded if any circuit is open
                    if state.get("state") == "open":
                        health["overall_status"] = "degraded"
        except ImportError:
            health["circuit_breakers"]["_note"] = "CircuitBreaker module not available"
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            logger.debug("Could not get circuit breaker status: %s", e)
            health["circuit_breakers"]["_error"] = "Health check failed"

        # Get fallback chain status
        try:
            from aragora.agents.fallback import get_local_fallback_providers, is_local_llm_available

            health["fallback"] = {
                "openrouter_available": _secret_configured("OPENROUTER_API_KEY"),
                "local_llm_available": is_local_llm_available(),
                "local_providers": get_local_fallback_providers(),
            }
        except ImportError:
            health["fallback"]["_note"] = "Fallback module not available"
        except (KeyError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.debug("Could not get fallback status: %s", e)
            health["fallback"]["_error"] = "Health check failed"

        # Get registered agent types and their availability
        try:
            from aragora.agents.registry import AgentRegistry, register_all_agents

            register_all_agents()
            all_agents = AgentRegistry.list_all()

            openrouter_available = _secret_configured("OPENROUTER_API_KEY")
            for agent_type, spec in all_agents.items():
                agent_health = {
                    "type": spec.get("type", "unknown"),
                    "requires_api_key": bool(spec.get("env_vars")),
                    "api_key_configured": False,
                    "available": False,
                }

                # Check if required API key is configured
                env_vars = spec.get("env_vars")
                missing = _missing_required_env_vars(env_vars)
                agent_health["api_key_configured"] = not missing
                if not missing:
                    agent_health["available"] = True
                else:
                    fallback_model = _OPENROUTER_FALLBACK_MODELS.get(agent_type)
                    uses_fallback = bool(openrouter_available and fallback_model)
                    agent_health["available"] = uses_fallback
                    agent_health["uses_openrouter_fallback"] = uses_fallback
                    agent_health["fallback_model"] = fallback_model if uses_fallback else None

                # Check circuit breaker state
                cb_state = health["circuit_breakers"].get(agent_type, {})
                if cb_state.get("state") == "open":
                    agent_health["available"] = False
                    agent_health["circuit_breaker_open"] = True

                health["agents"][agent_type] = agent_health
        except ImportError:
            health["agents"]["_note"] = "AgentRegistry not available"
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            logger.debug("Could not get agent registry: %s", e)
            health["agents"]["_error"] = "Health check failed"

        # Calculate summary
        available_count = sum(
            1
            for a in health["agents"].values()
            if isinstance(a, dict) and a.get("available", False)
        )
        total_count = sum(1 for a in health["agents"].values() if isinstance(a, dict))

        health["summary"] = {
            "available_agents": available_count,
            "total_agents": total_count,
            "availability_rate": (
                round(available_count / total_count, 2) if total_count > 0 else 0.0
            ),
        }

        # Downgrade status if too few agents available
        if total_count > 0 and available_count / total_count < 0.5:
            health["overall_status"] = "degraded"
        if available_count == 0 and total_count > 0:
            health["overall_status"] = "unhealthy"

        # Add cross-pollination subscriber health
        try:
            from aragora.events.cross_subscribers import get_cross_subscriber_manager

            manager = get_cross_subscriber_manager()
            stats = manager.get_stats()

            # Calculate subscriber health
            total_subs = len(stats)
            healthy_subs = sum(
                1
                for s in stats.values()
                if s.get("enabled") and s.get("circuit_breaker", {}).get("available", True)
            )

            health["cross_pollination"] = {
                "total_subscribers": total_subs,
                "healthy_subscribers": healthy_subs,
                "health_rate": round(healthy_subs / total_subs, 2) if total_subs > 0 else 1.0,
                "total_events_processed": sum(s.get("events_processed", 0) for s in stats.values()),
                "total_events_failed": sum(s.get("events_failed", 0) for s in stats.values()),
            }

            # Downgrade if cross-pollination unhealthy
            if total_subs > 0 and healthy_subs / total_subs < 0.5:
                if health["overall_status"] == "healthy":
                    health["overall_status"] = "degraded"
        except ImportError:
            health["cross_pollination"] = {"_note": "Cross-pollination module not available"}
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            logger.debug("Could not get cross-pollination status: %s", e)
            health["cross_pollination"] = {"_error": "Health check failed"}

        return json_response(health)

    @api_endpoint(
        method="GET",
        path="/api/v1/agents/availability",
        summary="Get agent availability based on configured API keys",
        tags=["Agents"],
    )
    @rate_limit(requests_per_minute=60, limiter_name="agent_availability")
    @handle_errors("get agent availability")
    def _get_agent_availability(self) -> HandlerResult:
        """Report agent availability based on configured secrets."""
        from aragora.agents.registry import AgentRegistry, register_all_agents

        register_all_agents()
        openrouter_available = _secret_configured("OPENROUTER_API_KEY")

        availability: dict[str, Any] = {
            "openrouter_available": openrouter_available,
            "agents": {},
        }

        for agent_type, spec in AgentRegistry.list_all().items():
            env_vars = spec.get("env_vars")
            missing = _missing_required_env_vars(env_vars)
            fallback_model = _OPENROUTER_FALLBACK_MODELS.get(agent_type)
            uses_openrouter = bool(openrouter_available and missing and fallback_model)

            availability["agents"][agent_type] = {
                "type": spec.get("type"),
                "env_vars": env_vars or "",
                "missing_env_vars": missing,
                "available": not missing or uses_openrouter,
                "uses_openrouter_fallback": uses_openrouter,
                "fallback_model": fallback_model if uses_openrouter else None,
            }

        return json_response(availability)

    # Remaining endpoint methods are provided by:
    # - AgentRankingsMixin (leaderboard, calibration LB, recent matches, compare)
    # - AgentProfilesMixin (profile, history, calibration, consistency, network, rivals, allies, moments, positions, domains, performance)
    # - AgentIntelligenceMixin (metadata, introspect, head-to-head, opponent-briefing)
    # - AgentFlipsMixin (agent flips, recent flips, flip summary)
