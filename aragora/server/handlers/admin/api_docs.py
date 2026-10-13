"""
API Documentation Handler.

Serves OpenAPI specification and route introspection endpoints:
- GET /api/v1/docs/openapi.json  — Full OpenAPI 3.1 spec (cached)
- GET /api/v1/docs/routes        — Lightweight route summary from handler registry
- GET /api/v1/docs/stats         — API statistics (endpoint counts by tag/method)

These endpoints power the /api-docs frontend page and provide
programmatic access to the API surface area.
"""

from __future__ import annotations

__all__ = ["ApiDocsHandler"]

import json
import logging
from typing import Any

from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
    ttl_cache,
)

logger = logging.getLogger(__name__)

# Cache the spec for 10 minutes (it rarely changes at runtime)
_SPEC_CACHE_TTL = 600


class ApiDocsHandler(BaseHandler):
    """Handler for API documentation and introspection endpoints."""

    ROUTES = [
        "/api/v1/docs/openapi.json",
        "/api/v1/docs/routes",
        "/api/v1/docs/stats",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the request."""
        if method != "GET":
            return False
        return path in self.ROUTES

    def handle(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route documentation requests."""
        if path == "/api/v1/docs/openapi.json":
            return self._get_openapi_spec()
        if path == "/api/v1/docs/routes":
            return self._get_routes(query_params)
        if path == "/api/v1/docs/stats":
            return self._get_stats()
        return None

    @ttl_cache(ttl_seconds=_SPEC_CACHE_TTL, key_prefix="api_docs_spec", skip_first=True)
    def _get_openapi_spec(self) -> HandlerResult:
        """Serve the full OpenAPI 3.1 specification."""
        try:
            from aragora.server.openapi_impl import generate_openapi_schema

            schema = generate_openapi_schema()
            body = json.dumps(schema, separators=(",", ":")).encode("utf-8")
            return HandlerResult(
                status_code=200,
                content_type="application/json",
                body=body,
                headers={"Cache-Control": "public, max-age=600"},
            )
        except ImportError:
            logger.warning("OpenAPI module not available for api_docs handler")
            return error_response("OpenAPI module not available", 503)
        except (ValueError, TypeError, KeyError, RuntimeError, OSError) as e:
            logger.warning("OpenAPI generation failed: %s", e)
            return error_response("Failed to generate OpenAPI spec", 500)

    def _get_routes(self, query_params: dict) -> HandlerResult:
        """Return a lightweight summary of all registered routes.

        Introspects the handler registry to list routes without
        requiring the full OpenAPI spec generation.

        Query params:
            tag: Filter by tag/category name (case-insensitive substring match)
            method: Filter by HTTP method (GET, POST, etc.)
        """
        try:
            routes = self._introspect_handler_routes()

            # Apply filters
            tag_filter = query_params.get("tag", "")
            method_filter = query_params.get("method", "")

            if tag_filter:
                tag_lower = tag_filter.lower()
                routes = [r for r in routes if tag_lower in r.get("tag", "").lower()]

            if method_filter:
                method_upper = method_filter.upper()
                routes = [r for r in routes if method_upper in r.get("methods", [])]

            return json_response(
                {
                    "total": len(routes),
                    "routes": routes,
                }
            )
        except (ImportError, RuntimeError, AttributeError) as e:
            logger.warning("Route introspection failed: %s", e)
            return error_response("Route introspection failed", 500)

    def _get_stats(self) -> HandlerResult:
        """Return API statistics: endpoint counts by tag and method."""
        try:
            from aragora.server.openapi_impl import generate_openapi_schema

            schema = generate_openapi_schema()
            paths = schema.get("paths", {})

            # Count by tag
            tag_counts: dict[str, int] = {}
            method_counts: dict[str, int] = {}
            total = 0

            for _path, methods in paths.items():
                for method, details in methods.items():
                    if method.startswith("x-") or method == "parameters":
                        continue
                    total += 1
                    method_upper = method.upper()
                    method_counts[method_upper] = method_counts.get(method_upper, 0) + 1

                    tags = details.get("tags", ["Untagged"])
                    for tag in tags:
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1

            # Sort tags by count descending
            sorted_tags = sorted(tag_counts.items(), key=lambda x: -x[1])

            return json_response(
                {
                    "total_endpoints": total,
                    "total_paths": len(paths),
                    "by_method": method_counts,
                    "by_tag": [{"tag": t, "count": c} for t, c in sorted_tags],
                }
            )
        except (ImportError, RuntimeError) as e:
            logger.warning("API stats generation failed: %s", e)
            return error_response("Stats generation failed", 500)

    def _introspect_handler_routes(self) -> list[dict[str, Any]]:
        """Introspect registered handlers to build route list.

        Returns a list of route dicts with path, methods, handler class name,
        and inferred tag.
        """
        from aragora.server.handlers._registry import ALL_HANDLERS
        from aragora.server.openapi_impl import TAG_INFERENCE_RULES

        routes: list[dict[str, Any]] = []
        seen_paths: set[str] = set()

        for handler_cls in ALL_HANDLERS:
            handler_name = handler_cls.__name__
            handler_routes = getattr(handler_cls, "ROUTES", [])

            for route_path in handler_routes:
                if route_path in seen_paths:
                    continue
                seen_paths.add(route_path)

                # Infer methods from can_handle if possible
                methods = self._infer_methods(handler_cls)

                # Infer tag from path
                tag = self._infer_tag(route_path, TAG_INFERENCE_RULES)

                # Get description from handler docstring
                doc = handler_cls.__doc__ or ""
                description = doc.strip().split("\n")[0] if doc.strip() else ""

                routes.append(
                    {
                        "path": route_path,
                        "methods": methods,
                        "handler": handler_name,
                        "tag": tag,
                        "description": description,
                    }
                )

        # Sort by path
        routes.sort(key=lambda r: r["path"])
        return routes

    def _infer_methods(self, handler_cls: type) -> list[str]:
        """Infer supported HTTP methods from handler class."""
        methods = []
        for method_name in (
            "handle_get",
            "handle_post",
            "handle_put",
            "handle_delete",
            "handle_patch",
        ):
            if hasattr(handler_cls, method_name):
                methods.append(method_name.replace("handle_", "").upper())

        # If no explicit handle_X methods, check can_handle or default to GET
        if not methods:
            methods = ["GET"]

        return methods

    def _infer_tag(self, path: str, rules: list[tuple[str, str]]) -> str:
        """Infer tag from path using TAG_INFERENCE_RULES."""
        # Strip version prefix for matching
        normalized = path
        for prefix in ("/api/v1/", "/api/v2/", "/api/"):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :]
                break

        for prefix, tag in rules:
            if normalized.startswith(prefix):
                return tag

        return "Other"
