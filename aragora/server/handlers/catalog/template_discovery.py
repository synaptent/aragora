"""
Template Discovery API handler.

Exposes deliberation templates via public API endpoints for browsing,
searching, and recommendation.

Endpoints:
- GET /api/v1/templates — list all templates, optional category/search filter
- GET /api/v1/templates/categories — category counts
- GET /api/v1/templates/recommend — recommend templates for a question
- GET /api/v1/templates/{name} — single template detail
"""

from __future__ import annotations

__all__ = [
    "TemplateDiscoveryHandler",
]

import logging
from typing import Any

from aragora.server.versioning.compat import strip_version_prefix

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
)
from aragora.rbac.decorators import require_permission
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter: 30 requests per minute per IP (public discovery endpoints)
_discovery_limiter = RateLimiter(requests_per_minute=30)


def _get_registry():
    """Get the global template registry (lazy import to avoid circular imports)."""
    from aragora.deliberation.templates.registry import _global_registry

    return _global_registry


class TemplateDiscoveryHandler(BaseHandler):
    """Handler for template discovery endpoints."""

    ROUTES: list[str] = [
        "/api/v1/templates",
        "/api/v1/templates/categories",
        "/api/v1/templates/recommend",
        "/api/v1/templates/*",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        normalized = strip_version_prefix(path)
        if normalized == "/api/templates":
            return True
        if normalized == "/api/templates/categories":
            return True
        if normalized == "/api/templates/recommend":
            return True
        if normalized.startswith("/api/templates/"):
            return True
        return False

    @require_permission("templates:read")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route template discovery requests."""
        normalized = strip_version_prefix(path)

        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _discovery_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded. Max 30 requests per minute.", 429)

        if normalized == "/api/templates/categories":
            return self._handle_categories()
        if normalized == "/api/templates/recommend":
            return self._handle_recommend(query_params)
        if normalized == "/api/templates":
            return self._handle_list(query_params)

        # /api/templates/{name} — single template detail
        if normalized.startswith("/api/templates/"):
            parts = normalized.split("/")
            # ["", "api", "templates", "{name}"]
            if len(parts) >= 4 and parts[3]:
                return self._handle_detail(parts[3])

        return None

    def _handle_list(self, query_params: dict[str, Any]) -> HandlerResult:
        """List all templates with optional category/search filtering."""
        registry = _get_registry()

        category = query_params.get("category")
        search = query_params.get("search")

        templates = registry.list(
            category=self._parse_category(category) if category else None,
            search=search,
        )

        return json_response(
            {
                "templates": [t.to_dict() for t in templates],
                "count": len(templates),
            }
        )

    def _handle_categories(self) -> HandlerResult:
        """Return categories with counts."""
        registry = _get_registry()
        categories = registry.categories()
        return json_response(
            {
                "categories": categories,
            }
        )

    def _handle_recommend(self, query_params: dict[str, Any]) -> HandlerResult:
        """Recommend templates for a given question."""
        question = query_params.get("question", "")
        if not question:
            return error_response("Missing 'question' query parameter", 400)

        domain = query_params.get("domain")
        registry = _get_registry()
        recommended = registry.recommend(question=question, domain=domain, limit=3)

        return json_response(
            {
                "recommended": [
                    {"name": t.name, "description": t.description, "category": t.category.value}
                    for t in recommended
                ],
                "question": question,
            }
        )

    def _handle_detail(self, name: str) -> HandlerResult:
        """Return a single template by name."""
        registry = _get_registry()
        template = registry.get(name)
        if template is None:
            return error_response(f"Template '{name}' not found", 404)
        return json_response(template.to_dict())

    def _parse_category(self, category_str: str | None):
        """Parse a category string to TemplateCategory enum."""
        if not category_str:
            return None
        from aragora.deliberation.templates.base import TemplateCategory

        try:
            return TemplateCategory(category_str)
        except ValueError:
            return None
