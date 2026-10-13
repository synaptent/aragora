"""
Skill Marketplace API Handlers.

Provides REST APIs for the skill marketplace:
- Skill search and discovery
- Skill publishing
- Skill installation and management
- Ratings and reviews

Endpoints:
- GET /api/v1/skills/marketplace/search - Search skills
- GET /api/v1/skills/marketplace/{skill_id} - Get skill details
- GET /api/v1/skills/marketplace/{skill_id}/versions - Get skill versions
- GET /api/v1/skills/marketplace/{skill_id}/ratings - Get skill ratings
- POST /api/v1/skills/marketplace/publish - Publish a skill
- POST /api/v1/skills/marketplace/{skill_id}/install - Install a skill
- DELETE /api/v1/skills/marketplace/{skill_id}/install - Uninstall a skill
- POST /api/v1/skills/marketplace/{skill_id}/rate - Rate a skill
- PUT /api/v1/skills/marketplace/{skill_id}/verify - Set skill verified (admin)
- DELETE /api/v1/skills/marketplace/{skill_id}/verify - Revoke verification (admin)
- GET /api/v1/skills/marketplace/installed - List installed skills
- GET /api/v1/skills/marketplace/stats - Get marketplace statistics
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from aragora.rbac.models import AuthorizationContext
from aragora.server.handlers.base import (
    HandlerResult,
    error_response,
    json_response,
)
from aragora.server.handlers.secure import ForbiddenError, SecureHandler, UnauthorizedError
from aragora.server.versioning.compat import strip_version_prefix
from aragora.server.validation.query_params import safe_query_int

logger = logging.getLogger(__name__)


class SkillMarketplaceHandler(SecureHandler):
    """Handler for skill marketplace endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    RESOURCE_TYPE = "skills"

    ROUTES = [
        "/api/skills/marketplace/search",
        "/api/skills/marketplace/publish",
        "/api/skills/marketplace/installed",
        "/api/skills/marketplace/stats",
    ]

    PATTERN_PREFIXES = [
        "/api/skills/marketplace/",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can handle the given path."""
        path = strip_version_prefix(path)

        if path in self.ROUTES:
            return True

        for prefix in self.PATTERN_PREFIXES:
            if path.startswith(prefix):
                return True

        return False

    async def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
        method: str = "GET",
        body: dict[str, Any] | None = None,
    ) -> HandlerResult | None:
        """Route marketplace requests."""
        # Get auth context (some endpoints allow anonymous)
        auth_context: AuthorizationContext | None = None
        try:
            auth_context = await self.get_auth_context(handler, require_auth=False)
        except (UnauthorizedError, ForbiddenError):
            auth_context = None

        def _is_authenticated(context: AuthorizationContext | dict[str, Any] | None) -> bool:
            if context is None:
                return False
            if isinstance(context, dict):
                user_id = context.get("user_id")
            else:
                user_id = getattr(context, "user_id", None)
            return bool(user_id) and user_id != "anonymous"

        path = strip_version_prefix(path)

        # Search skills (public)
        if path == "/api/skills/marketplace/search":
            return await self._search_skills(query_params)

        # Get marketplace stats (public)
        if path == "/api/skills/marketplace/stats":
            return await self._get_stats()

        # List installed skills (requires auth)
        if path == "/api/skills/marketplace/installed":
            if not _is_authenticated(auth_context):
                return error_response("Authentication required", 401)
            try:
                self.check_permission(auth_context, "skills:read")
            except ForbiddenError:
                return error_response("Permission denied", 403)
            return await self._list_installed(auth_context)

        # Publish skill (requires auth)
        if path == "/api/skills/marketplace/publish" and method == "POST":
            if not _is_authenticated(auth_context):
                return error_response("Authentication required", 401)
            try:
                self.check_permission(auth_context, "skills:publish")
            except ForbiddenError:
                return error_response("Permission denied", 403)
            return await self._publish_skill(body or {}, auth_context)

        # Skill-specific endpoints
        if path.startswith("/api/skills/marketplace/"):
            parts = path.split("/")
            if len(parts) >= 5:
                skill_id = parts[4]

                # Get skill details (public)
                if len(parts) == 5 and method == "GET":
                    return await self._get_skill(skill_id)

                # Get skill versions
                if len(parts) == 6 and parts[5] == "versions" and method == "GET":
                    return await self._get_versions(skill_id)

                # Get skill ratings
                if len(parts) == 6 and parts[5] == "ratings" and method == "GET":
                    return await self._get_ratings(skill_id, query_params)

                # Install skill
                if len(parts) == 6 and parts[5] == "install" and method == "POST":
                    if not _is_authenticated(auth_context):
                        return error_response("Authentication required", 401)
                    try:
                        self.check_permission(auth_context, "skills:install")
                    except ForbiddenError:
                        return error_response("Permission denied", 403)
                    return await self._install_skill(skill_id, body or {}, auth_context)

                # Uninstall skill
                if len(parts) == 6 and parts[5] == "install" and method == "DELETE":
                    if not _is_authenticated(auth_context):
                        return error_response("Authentication required", 401)
                    try:
                        self.check_permission(auth_context, "skills:install")
                    except ForbiddenError:
                        return error_response("Permission denied", 403)
                    return await self._uninstall_skill(skill_id, auth_context)

                # Rate skill
                if len(parts) == 6 and parts[5] == "rate" and method == "POST":
                    if not _is_authenticated(auth_context):
                        return error_response("Authentication required", 401)
                    try:
                        self.check_permission(auth_context, "skills:rate")
                    except ForbiddenError:
                        return error_response("Permission denied", 403)
                    return await self._rate_skill(skill_id, body or {}, auth_context)

                # Verify skill (admin)
                if len(parts) == 6 and parts[5] == "verify" and method == "PUT":
                    if not _is_authenticated(auth_context):
                        return error_response("Authentication required", 401)
                    try:
                        self.check_permission(auth_context, "skills:admin")
                    except ForbiddenError:
                        return error_response("Permission denied", 403)
                    return await self._set_verification(skill_id, True, auth_context)

                # Revoke verification (admin)
                if len(parts) == 6 and parts[5] == "verify" and method == "DELETE":
                    if not _is_authenticated(auth_context):
                        return error_response("Authentication required", 401)
                    try:
                        self.check_permission(auth_context, "skills:admin")
                    except ForbiddenError:
                        return error_response("Permission denied", 403)
                    return await self._set_verification(skill_id, False, auth_context)

        return None

    async def _search_skills(self, query_params: dict[str, Any]) -> HandlerResult:
        """Search for skills in the marketplace."""
        try:
            from aragora.skills.marketplace import SkillCategory, SkillTier, get_marketplace

            marketplace = get_marketplace()

            # Parse query params
            query = query_params.get("q", "")
            category_str = query_params.get("category")
            tier_str = query_params.get("tier")
            tags = query_params.get("tags", "").split(",") if query_params.get("tags") else None
            author_id = query_params.get("author")
            sort_by = query_params.get("sort", "rating")
            limit = safe_query_int(query_params, "limit", default=20, max_val=100)
            offset = safe_query_int(query_params, "offset", default=0, max_val=100000)

            # Parse enums
            category = SkillCategory(category_str) if category_str else None
            tier = SkillTier(tier_str) if tier_str else None

            results = await marketplace.search(
                query=query,
                category=category,
                tier=tier,
                tags=tags,
                author_id=author_id,
                sort_by=sort_by,
                limit=limit,
                offset=offset,
            )

            return json_response(
                {
                    "query": query,
                    "count": len(results),
                    "limit": limit,
                    "offset": offset,
                    "results": [r.to_dict() for r in results],
                }
            )

        except ImportError:
            return error_response("Skill marketplace not available", 503)
        except (KeyError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.error("Error searching skills: %s", e)
            return error_response("Search operation failed", 500)

    async def _get_skill(self, skill_id: str) -> HandlerResult:
        """Get skill details."""
        try:
            from aragora.skills.marketplace import get_marketplace

            marketplace = get_marketplace()
            listing = await marketplace.get_skill(skill_id)

            if not listing:
                return error_response("Skill not found", 404)

            return json_response(listing.to_dict())

        except ImportError:
            return error_response("Skill marketplace not available", 503)
        except (KeyError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.error("Error getting skill: %s", e)
            return error_response("Failed to retrieve skill", 500)

    async def _get_versions(self, skill_id: str) -> HandlerResult:
        """Get skill versions."""
        try:
            from aragora.skills.marketplace import get_marketplace

            marketplace = get_marketplace()
            versions = await marketplace.get_versions(skill_id)

            if not versions:
                return error_response("Skill not found", 404)

            return json_response(
                {
                    "skill_id": skill_id,
                    "versions": [v.to_dict() for v in versions],
                }
            )

        except ImportError:
            return error_response("Skill marketplace not available", 503)
        except (KeyError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.error("Error getting versions: %s", e)
            return error_response("Failed to retrieve versions", 500)

    async def _get_ratings(self, skill_id: str, query_params: dict[str, Any]) -> HandlerResult:
        """Get skill ratings."""
        try:
            from aragora.skills.marketplace import get_marketplace

            marketplace = get_marketplace()

            limit = safe_query_int(query_params, "limit", default=20, max_val=100)
            offset = safe_query_int(query_params, "offset", default=0, max_val=100000)

            ratings = await marketplace.get_ratings(skill_id, limit=limit, offset=offset)

            return json_response(
                {
                    "skill_id": skill_id,
                    "count": len(ratings),
                    "ratings": [r.to_dict() for r in ratings],
                }
            )

        except ImportError:
            return error_response("Skill marketplace not available", 503)
        except (KeyError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.error("Error getting ratings: %s", e)
            return error_response("Failed to retrieve ratings", 500)

    async def _publish_skill(
        self, body: dict[str, Any], auth_context: AuthorizationContext | dict[str, Any]
    ) -> HandlerResult:
        """Publish a skill to the marketplace."""
        try:
            from aragora.skills.marketplace import SkillCategory, SkillTier
            from aragora.skills.publisher import SkillPublisher
            from aragora.skills.registry import get_skill_registry

            # Get required fields
            skill_name = body.get("skill_name")
            if not skill_name:
                return error_response("skill_name is required", 400)

            # Get skill from registry
            registry = get_skill_registry()
            skill = registry.get(skill_name)

            if not skill:
                return error_response(f"Skill '{skill_name}' not found in registry", 404)

            # Get optional fields
            category_str = body.get("category", "custom")
            tier_str = body.get("tier", "free")
            changelog = body.get("changelog", "Initial release")

            try:
                category = SkillCategory(category_str)
            except ValueError:
                return error_response(f"Invalid category: {category_str}", 400)

            try:
                tier = SkillTier(tier_str)
            except ValueError:
                return error_response(f"Invalid tier: {tier_str}", 400)

            # Publish
            publisher = SkillPublisher()
            user_id = getattr(auth_context, "user_id", None) or (
                auth_context.get("user_id") if isinstance(auth_context, dict) else None
            )
            display_name = getattr(auth_context, "display_name", None)
            if display_name is None and isinstance(auth_context, dict):
                display_name = auth_context.get("display_name")
            display_name = display_name or user_id
            success, listing, issues = await publisher.publish(
                skill=skill,
                author_id=user_id,
                author_name=display_name,
                category=category,
                tier=tier,
                changelog=changelog,
                homepage_url=body.get("homepage_url"),
                repository_url=body.get("repository_url"),
                documentation_url=body.get("documentation_url"),
            )

            if not success:
                return json_response(
                    {
                        "success": False,
                        "issues": [i.to_dict() for i in issues],
                    },
                    status=400,
                )

            return json_response(
                {
                    "success": True,
                    "skill": listing.to_dict() if listing else None,
                    "issues": [i.to_dict() for i in issues],
                }
            )

        except ImportError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Required module not available", 503)
        except (KeyError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.error("Error publishing skill: %s", e)
            return error_response("Publish operation failed", 500)

    async def _install_skill(
        self,
        skill_id: str,
        body: dict[str, Any],
        auth_context: AuthorizationContext | dict[str, Any],
    ) -> HandlerResult:
        """Install a skill."""
        try:
            from aragora.skills.installer import SkillInstaller

            installer = SkillInstaller()

            tenant_id = (
                getattr(auth_context, "tenant_id", None)
                or (auth_context.get("tenant_id") if isinstance(auth_context, dict) else None)
                or "default"
            )
            user_id = getattr(auth_context, "user_id", None) or (
                auth_context.get("user_id") if isinstance(auth_context, dict) else None
            )
            version = body.get("version")
            permissions = getattr(auth_context, "permissions", None)
            if permissions is None and isinstance(auth_context, dict):
                permissions = auth_context.get("permissions", set())
            permissions = list(permissions or [])

            result = await installer.install(
                skill_id=skill_id,
                tenant_id=tenant_id,
                user_id=user_id,
                version=version,
                permissions=permissions,
            )

            if not result.success:
                return json_response(
                    {
                        "success": False,
                        "error": result.error,
                    },
                    status=400,
                )

            return json_response(result.to_dict())

        except ImportError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Required module not available", 503)
        except (KeyError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.error("Error installing skill: %s", e)
            return error_response("Installation failed", 500)

    async def _uninstall_skill(
        self,
        skill_id: str,
        auth_context: AuthorizationContext | dict[str, Any],
    ) -> HandlerResult:
        """Uninstall a skill."""
        try:
            from aragora.skills.installer import SkillInstaller

            installer = SkillInstaller()

            tenant_id = (
                getattr(auth_context, "tenant_id", None)
                or (auth_context.get("tenant_id") if isinstance(auth_context, dict) else None)
                or "default"
            )
            user_id = getattr(auth_context, "user_id", None) or (
                auth_context.get("user_id") if isinstance(auth_context, dict) else None
            )
            permissions = getattr(auth_context, "permissions", None)
            if permissions is None and isinstance(auth_context, dict):
                permissions = auth_context.get("permissions", set())
            permissions = list(permissions or [])

            success = await installer.uninstall(
                skill_id=skill_id,
                tenant_id=tenant_id,
                user_id=user_id,
                permissions=permissions,
            )

            if not success:
                return error_response("Failed to uninstall skill", 400)

            return json_response(
                {
                    "success": True,
                    "skill_id": skill_id,
                    "uninstalled_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        except ImportError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Required module not available", 503)
        except (KeyError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.error("Error uninstalling skill: %s", e)
            return error_response("Uninstallation failed", 500)

    async def _rate_skill(
        self,
        skill_id: str,
        body: dict[str, Any],
        auth_context: AuthorizationContext | dict[str, Any],
    ) -> HandlerResult:
        """Rate a skill."""
        try:
            from aragora.skills.marketplace import get_marketplace

            rating = body.get("rating")
            if not rating or not isinstance(rating, int) or not 1 <= rating <= 5:
                return error_response("rating must be an integer between 1 and 5", 400)

            review = body.get("review")
            user_id = getattr(auth_context, "user_id", None) or (
                auth_context.get("user_id") if isinstance(auth_context, dict) else None
            )

            marketplace = get_marketplace()
            skill_rating = await marketplace.rate(
                skill_id=skill_id,
                user_id=user_id,
                rating=rating,
                review=review,
            )

            return json_response(skill_rating.to_dict())

        except ValueError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request", 400)
        except ImportError:
            return error_response("Skill marketplace not available", 503)
        except (KeyError, TypeError, AttributeError, OSError) as e:
            logger.error("Error rating skill: %s", e)
            return error_response("Rating submission failed", 500)

    async def _set_verification(
        self,
        skill_id: str,
        verified: bool,
        auth_context: AuthorizationContext | dict[str, Any],
    ) -> HandlerResult:
        """Set or revoke verification status for a skill."""
        try:
            from aragora.skills.marketplace import get_marketplace

            marketplace = get_marketplace()

            # Check skill exists
            listing = await marketplace.get_skill(skill_id)
            if not listing:
                return error_response("Skill not found", 404)

            user_id = getattr(auth_context, "user_id", None) or (
                auth_context.get("user_id") if isinstance(auth_context, dict) else None
            )

            success = await marketplace.set_verified(skill_id, verified)

            if not success:
                return error_response("Failed to update verification status", 500)

            logger.info(
                "Skill %s verification changed to %s by %s",
                skill_id,
                verified,
                user_id,
            )

            return json_response(
                {
                    "skill_id": skill_id,
                    "is_verified": verified,
                    "changed_by": user_id,
                    "changed_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        except ImportError:
            return error_response("Skill marketplace not available", 503)
        except (KeyError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.error("Error updating verification status: %s", e)
            return error_response("Verification update failed", 500)

    async def _list_installed(self, auth_context: AuthorizationContext) -> HandlerResult:
        """List installed skills for the tenant."""
        try:
            from aragora.skills.installer import SkillInstaller

            installer = SkillInstaller()
            tenant_id = getattr(auth_context, "tenant_id", None) or "default"

            skills = await installer.get_installed(tenant_id)

            return json_response(
                {
                    "tenant_id": tenant_id,
                    "count": len(skills),
                    "skills": [s.to_dict() for s in skills],
                }
            )

        except ImportError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Required module not available", 503)
        except (KeyError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.error("Error listing installed skills: %s", e)
            return error_response("Failed to list skills", 500)

    async def _get_stats(self) -> HandlerResult:
        """Get marketplace statistics."""
        try:
            from aragora.skills.marketplace import get_marketplace

            marketplace = get_marketplace()
            stats = await marketplace.get_stats()

            return json_response(stats)

        except ImportError:
            return error_response("Skill marketplace not available", 503)
        except (KeyError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.error("Error getting stats: %s", e)
            return error_response("Failed to retrieve statistics", 500)
