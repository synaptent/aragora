"""Feature flags handler for reading flag values.

This is the public-facing feature flag endpoint (read-only).
For admin operations (toggle/set), see admin/feature_flags.py.

Endpoints:
- GET /api/v1/feature-flags - List all feature flags with current values
- GET /api/v1/feature-flags/:name - Get a specific flag value
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.rbac.decorators import require_permission
from aragora.server.handlers.base import BaseHandler, HandlerResult, error_response, json_response
from aragora.server.versioning.compat import strip_version_prefix

logger = logging.getLogger(__name__)

# Lazy imports for feature flag system
try:
    from aragora.config.feature_flags import (
        FlagCategory,
        FlagStatus,
        get_flag_registry,
    )

    FLAGS_AVAILABLE = True
except ImportError:
    FLAGS_AVAILABLE = False
    get_flag_registry = None  # type: ignore[assignment]
    FlagCategory = None  # type: ignore[assignment,misc]
    FlagStatus = None  # type: ignore[assignment,misc]


class FeatureFlagsHandler(BaseHandler):
    """Handle public feature flag read endpoints."""

    ROUTES = [
        "/api/v1/feature-flags",
        "/api/v1/feature-flags/*",
    ]

    def can_handle(self, path: str) -> bool:
        stripped = strip_version_prefix(path)
        return stripped == "/api/feature-flags" or stripped.startswith("/api/feature-flags/")

    @require_permission("admin:read")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        if handler.command != "GET":
            return error_response("Method not allowed", 405)

        if not FLAGS_AVAILABLE:
            return error_response("Feature flag system not available", 503)

        stripped = strip_version_prefix(path)

        if stripped == "/api/feature-flags":
            return self._list_flags(query_params)

        if stripped.startswith("/api/feature-flags/"):
            name = stripped.split("/api/feature-flags/", 1)[1]
            if not name:
                return error_response("Flag name is required", 400)
            return self._get_flag(name)

        return None

    def _list_flags(self, query_params: dict[str, Any]) -> HandlerResult:
        registry = get_flag_registry()
        category_str = query_params.get("category")
        category_filter = None
        if category_str:
            try:
                category_filter = FlagCategory(category_str)
            except ValueError:
                valid = [c.value for c in FlagCategory]
                return error_response(f"Invalid category. Valid: {', '.join(valid)}", 400)

        flags = registry.get_all_flags(category=category_filter)
        flag_list = []
        for flag in flags:
            current_value = registry.get_value(flag.name, flag.default)
            flag_list.append(
                {
                    "name": flag.name,
                    "value": current_value,
                    "description": flag.description,
                    "category": flag.category.value,
                    "status": flag.status.value,
                }
            )

        return json_response(
            {
                "flags": flag_list,
                "total": len(flag_list),
            }
        )

    def _get_flag(self, name: str) -> HandlerResult:
        registry = get_flag_registry()
        definition = registry.get_definition(name)
        if not definition:
            return error_response(f"Flag not found: {name}", 404)

        current_value = registry.get_value(name, definition.default)
        return json_response(
            {
                "name": definition.name,
                "value": current_value,
                "description": definition.description,
                "category": definition.category.value,
                "status": definition.status.value,
            }
        )


__all__ = ["FeatureFlagsHandler"]
