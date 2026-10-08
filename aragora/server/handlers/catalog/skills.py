"""
Skills endpoint handlers.

Endpoints:
- GET /api/skills - List all registered skills
- GET /api/skills/:name - Get skill details
- POST /api/skills/invoke - Invoke a skill by name
- GET /api/skills/:name/metrics - Get skill execution metrics
"""

from __future__ import annotations

__all__ = [
    "SkillsHandler",
]

import asyncio
import logging
from typing import Any

from aragora.server.versioning.compat import strip_version_prefix

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from aragora.rbac.decorators import require_permission
from ..utils import parse_json_body
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter for skill endpoints (30 invocations per minute)
_skills_limiter = RateLimiter(requests_per_minute=30)

# Lazy imports for skills system
get_skill_registry: Any
SkillRegistry: Any
SkillContext: Any
SkillStatus: Any
try:
    from aragora.skills import (  # type: ignore[no-redef]
        SkillContext,
        SkillRegistry,
        SkillStatus,
        get_skill_registry,
    )

    SKILLS_AVAILABLE = True
except ImportError:
    SKILLS_AVAILABLE = False
    get_skill_registry = None
    SkillRegistry = None
    SkillContext = None
    SkillStatus = None


class SkillsHandler(BaseHandler):
    """Handler for skills system endpoints."""

    ROUTES: list[str] = [
        "/api/skills",
        "/api/skills/invoke",
        "/api/skills/*/invoke",
        "/api/skills/*/metrics",
        "/api/skills/*",  # Must be last due to wildcard
    ]

    # Spec-only verb declarations for routes whose dispatch is dynamic
    # (path.endswith checks in handle_post); read by openapi_impl, not
    # used for request routing.
    _ROUTE_MAP: dict[str, Any] = {
        "POST /api/skills/invoke": None,
        "POST /api/skills/*/invoke": None,
    }

    def __init__(self, server_context: dict[str, Any]):
        """Initialize with server context."""
        super().__init__(server_context)
        self._registry: SkillRegistry | None = None

    def _get_registry(self) -> SkillRegistry | None:
        """Get or create the skill registry singleton."""
        if self._registry is None and SKILLS_AVAILABLE and get_skill_registry:
            self._registry = get_skill_registry()
        return self._registry

    @handle_errors("skills GET request")
    @require_permission("debates:read")
    async def handle_get(self, path: str, request: Any) -> HandlerResult:
        """Handle GET requests for skills endpoints."""
        path = strip_version_prefix(path)

        if not SKILLS_AVAILABLE:
            return error_response(
                "Skills system not available",
                503,
                code="SKILLS_UNAVAILABLE",
            )

        # Rate limit check
        client_ip = get_client_ip(request)
        if not _skills_limiter.is_allowed(client_ip):
            return error_response(
                "Rate limit exceeded for skills endpoints",
                429,
                code="RATE_LIMITED",
            )

        # GET /api/skills - List all skills
        if path == "/api/skills":
            return await self._list_skills(request)

        # GET /api/skills/:name/metrics
        if "/metrics" in path:
            parts = path.split("/")
            if len(parts) >= 4:
                skill_name = parts[3]
                return await self._get_skill_metrics(skill_name, request)

        # GET /api/skills/:name - Get skill details
        parts = path.split("/")
        if len(parts) >= 4:
            skill_name = parts[3]
            return await self._get_skill(skill_name, request)

        return error_response(f"Unknown skills endpoint: {path}", 404)

    @handle_errors("skills POST request")
    @require_permission("debates:write")
    async def handle_post(self, path: str, request: Any) -> HandlerResult:
        """Handle POST requests for skills endpoints."""
        path = strip_version_prefix(path)

        if not SKILLS_AVAILABLE:
            return error_response(
                "Skills system not available",
                503,
                code="SKILLS_UNAVAILABLE",
            )

        # Rate limit check (stricter for invocations)
        client_ip = get_client_ip(request)
        if not _skills_limiter.is_allowed(client_ip):
            return error_response(
                "Rate limit exceeded for skill invocations",
                429,
                code="RATE_LIMITED",
            )

        # POST /api/skills/invoke (skill name in body)
        if path == "/api/skills/invoke":
            return await self._invoke_skill(request)

        # POST /api/skills/:name/invoke (skill name in URL)
        if path.endswith("/invoke"):
            parts = path.split("/")
            # Expected: ['', 'api', 'skills', '<name>', 'invoke']
            if len(parts) >= 5:
                skill_name = parts[3]
                return await self._invoke_skill(request, skill_name_override=skill_name)

        return error_response(f"Unknown skills endpoint: {path}", 404)

    @require_permission("skills:read")
    async def _list_skills(self, request: Any) -> HandlerResult:
        """List all registered skills.

        Query params:
            limit: Max results (default: 50, max: 500)
            offset: Pagination offset (default: 0)
        """
        registry = self._get_registry()
        if not registry:
            return error_response(
                "Skill registry not available",
                503,
                code="REGISTRY_UNAVAILABLE",
            )

        # Extract pagination params
        limit_str = self.get_query_param(request, "limit", "50")
        offset_str = self.get_query_param(request, "offset", "0")
        limit = max(1, min(500, int(limit_str or 50)))
        offset = max(0, int(offset_str or 0))

        all_skills = []
        for manifest in registry.list_skills():
            all_skills.append(
                {
                    "name": manifest.name,
                    "version": manifest.version,
                    "description": manifest.description or "",
                    "capabilities": [cap.value for cap in manifest.capabilities],
                    "input_schema": manifest.input_schema or {},
                    "tags": manifest.tags,
                }
            )

        total = len(all_skills)
        paginated = all_skills[offset : offset + limit]

        return json_response(
            {
                "skills": paginated,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )

    @require_permission("skills:read")
    async def _get_skill(self, name: str, request: Any) -> HandlerResult:
        """Get details for a specific skill."""
        registry = self._get_registry()
        if not registry:
            return error_response(
                "Skill registry not available",
                503,
                code="REGISTRY_UNAVAILABLE",
            )

        skill = registry.get(name)
        if not skill:
            return error_response(
                f"Skill not found: {name}",
                404,
                code="SKILL_NOT_FOUND",
            )

        manifest = skill.manifest
        return json_response(
            {
                "name": manifest.name,
                "version": manifest.version,
                "description": manifest.description or "",
                "capabilities": [cap.value for cap in manifest.capabilities],
                "input_schema": manifest.input_schema or {},
                "output_schema": manifest.output_schema or {},
                "rate_limit_per_minute": manifest.rate_limit_per_minute,
                "timeout_seconds": manifest.max_execution_time_seconds,
                "tags": manifest.tags,
            }
        )

    @require_permission("skills:read")
    async def _get_skill_metrics(self, name: str, request: Any) -> HandlerResult:
        """Get execution metrics for a specific skill."""
        registry = self._get_registry()
        if not registry:
            return error_response(
                "Skill registry not available",
                503,
                code="REGISTRY_UNAVAILABLE",
            )

        skill = registry.get(name)
        if not skill:
            return error_response(
                f"Skill not found: {name}",
                404,
                code="SKILL_NOT_FOUND",
            )

        # Get metrics from registry
        metrics = registry.get_metrics(name)
        if not metrics:
            return json_response(
                {
                    "skill": name,
                    "total_invocations": 0,
                    "successful_invocations": 0,
                    "failed_invocations": 0,
                    "average_latency_ms": 0,
                    "last_invoked": None,
                }
            )

        return json_response(
            {
                "skill": name,
                "total_invocations": metrics.get("total_invocations", 0),
                "successful_invocations": metrics.get("successful_invocations", 0),
                "failed_invocations": metrics.get("failed_invocations", 0),
                "average_latency_ms": metrics.get("average_latency_ms", 0),
                "last_invoked": metrics.get("last_invoked").isoformat()
                if metrics.get("last_invoked")
                else None,
            }
        )

    @require_permission("skills:invoke")
    async def _invoke_skill(
        self, request: Any, skill_name_override: str | None = None
    ) -> HandlerResult:
        """Invoke a skill by name.

        Args:
            request: The HTTP request object.
            skill_name_override: If provided, use this as the skill name
                instead of reading from the request body. Supports the
                POST /api/skills/:name/invoke URL pattern.
        """
        registry = self._get_registry()
        if not registry:
            return error_response(
                "Skill registry not available",
                503,
                code="REGISTRY_UNAVAILABLE",
            )

        # Parse request body
        if hasattr(request, "json"):
            # aiohttp request - use safe parser
            body, err = await parse_json_body(request, context="invoke_skill")
            if err:
                return error_response("Invalid JSON body", 400)
        else:
            body = request.get("body", {})

        skill_name = skill_name_override or body.get("skill")
        if not skill_name:
            return error_response("Missing required field: skill", 400)

        input_data = body.get("input", {})
        user_id = body.get("user_id", "api")
        permissions = set(body.get("permissions", ["skills:invoke"]))
        timeout = body.get("timeout", 30.0)

        # Validate skill exists
        skill = registry.get(skill_name)
        if not skill:
            return error_response(
                f"Skill not found: {skill_name}",
                404,
                code="SKILL_NOT_FOUND",
            )

        # Create skill context
        ctx = SkillContext(
            user_id=user_id,
            permissions=list(permissions),
            config=body.get("metadata", {}),
        )

        # Invoke with timeout
        try:
            result = await asyncio.wait_for(
                registry.invoke(skill_name, input_data, ctx),
                timeout=min(timeout, 60.0),  # Cap at 60 seconds
            )

            # Compute execution time in ms from duration_seconds
            exec_time_ms = int(result.duration_seconds * 1000) if result.duration_seconds else None

            if result.status == SkillStatus.SUCCESS:
                return json_response(
                    {
                        "status": "success",
                        "output": result.data,
                        "execution_time_ms": exec_time_ms,
                        "metadata": result.metadata or {},
                    }
                )
            elif result.status == SkillStatus.FAILURE:
                return json_response(
                    {
                        "status": "error",
                        "error": result.error_message or "Unknown error",
                        "execution_time_ms": exec_time_ms,
                    },
                    status=500,
                )
            elif result.status == SkillStatus.RATE_LIMITED:
                return error_response(
                    result.error_message or "Skill rate limited",
                    429,
                    code="SKILL_RATE_LIMITED",
                )
            elif result.status == SkillStatus.PERMISSION_DENIED:
                return error_response(
                    result.error_message or "Permission denied",
                    403,
                    code="PERMISSION_DENIED",
                )
            else:
                return json_response(
                    {
                        "status": result.status.value,
                        "output": result.data,
                        "error": result.error_message,
                        "execution_time_ms": exec_time_ms,
                    }
                )

        except asyncio.TimeoutError:
            return error_response(
                f"Skill invocation timed out after {timeout}s",
                408,
                code="TIMEOUT",
            )
        except (RuntimeError, OSError, ValueError, TypeError, AttributeError) as e:
            logger.exception("Skill invocation error for %s: %s", skill_name, e)
            return error_response(
                "Skill invocation failed",
                500,
                code="INVOCATION_ERROR",
            )
