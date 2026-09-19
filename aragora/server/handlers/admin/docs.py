"""
API documentation endpoint handlers.

Endpoints:
- GET /api/openapi - OpenAPI 3.0 JSON specification
- GET /api/openapi.json - OpenAPI 3.0 JSON specification
- GET /api/openapi.yaml - OpenAPI 3.0 YAML specification
- GET /api/postman.json - Postman collection export
- GET /api/docs - Swagger UI interactive documentation
- GET /api/redoc - ReDoc API documentation viewer

Extracted from system.py for better modularity.
"""

from __future__ import annotations

__all__ = [
    "DocsHandler",
    "CACHE_TTL_OPENAPI",
]

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    safe_error_message,
    ttl_cache,
)

logger = logging.getLogger(__name__)

# Cache TTL for OpenAPI spec (rarely changes)
CACHE_TTL_OPENAPI = 3600


class DocsHandler(BaseHandler):
    """Handler for API documentation endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/openapi",
        "/api/openapi.json",
        "/api/openapi.yaml",
        "/api/postman.json",
        "/api/docs",
        "/api/docs/",
        "/api/redoc",
        "/api/redoc/",
        "/api/v1/openapi",
        "/api/v1/openapi.json",
        "/api/v1/openapi.yaml",
        "/api/v1/postman.json",
        "/api/v1/docs",
        "/api/v1/docs/",
        "/api/v1/redoc",
        "/api/v1/redoc/",
    ]

    # Unversioned paths for direct matching (used by frontend)
    _OPENAPI_JSON_PATHS = {
        "/api/openapi",
        "/api/openapi.json",
        "/api/v1/openapi",
        "/api/v1/openapi.json",
    }
    _OPENAPI_YAML_PATHS = {"/api/openapi.yaml", "/api/v1/openapi.yaml"}
    _POSTMAN_PATHS = {"/api/postman.json", "/api/v1/postman.json"}
    _DOCS_PATHS = {"/api/docs", "/api/docs/", "/api/v1/docs", "/api/v1/docs/"}
    _REDOC_PATHS = {"/api/redoc", "/api/redoc/", "/api/v1/redoc", "/api/v1/redoc/"}

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the given path."""
        return path in self.ROUTES

    def handle(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route documentation endpoint requests."""
        if path in self._OPENAPI_JSON_PATHS:
            return self._get_openapi_spec("json")
        if path in self._OPENAPI_YAML_PATHS:
            return self._get_openapi_spec("yaml")
        if path in self._POSTMAN_PATHS:
            return self._get_postman_collection()
        if path in self._DOCS_PATHS:
            return self._get_swagger_ui()
        if path in self._REDOC_PATHS:
            return self._get_redoc()
        return None

    @ttl_cache(ttl_seconds=CACHE_TTL_OPENAPI, key_prefix="openapi_spec", skip_first=True)
    def _get_openapi_spec(self, format: str = "json") -> HandlerResult:
        """Get OpenAPI specification.

        Args:
            format: Output format - 'json' or 'yaml'

        Returns:
            OpenAPI 3.0 schema in requested format.
        """
        try:
            from aragora.server.openapi import handle_openapi_request

            content, content_type = handle_openapi_request(format=format)
            return HandlerResult(
                status_code=200,
                content_type=content_type,
                body=content.encode("utf-8") if isinstance(content, str) else content,
            )
        except ImportError:
            return error_response("OpenAPI module not available", 503)
        except (ValueError, TypeError, KeyError, RuntimeError, OSError) as e:
            logger.exception("OpenAPI generation failed: %s", e)
            return error_response(safe_error_message(e, "OpenAPI generation"), 500)

    def _get_swagger_ui(self) -> HandlerResult:
        """Serve Swagger UI for interactive API documentation.

        Returns an HTML page that loads Swagger UI from CDN and points it
        to the /api/openapi.json endpoint.

        Returns:
            HTML page with embedded Swagger UI
        """
        swagger_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Aragora API Documentation</title>
    <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
    <style>
        html { box-sizing: border-box; overflow-y: scroll; }
        *, *:before, *:after { box-sizing: inherit; }
        body { margin: 0; background: #fafafa; }
        .swagger-ui .topbar { display: none; }
        .swagger-ui .info { margin: 20px 0; }
        .swagger-ui .info .title { font-size: 2em; }
    </style>
</head>
<body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
    <script>
        window.onload = function() {
            window.ui = SwaggerUIBundle({
                url: "/api/v1/openapi.json",
                dom_id: '#swagger-ui',
                deepLinking: true,
                presets: [
                    SwaggerUIBundle.presets.apis,
                    SwaggerUIStandalonePreset
                ],
                plugins: [
                    SwaggerUIBundle.plugins.DownloadUrl
                ],
                layout: "StandaloneLayout",
                validatorUrl: null,
                docExpansion: "list",
                defaultModelsExpandDepth: 1,
                displayRequestDuration: true,
                filter: true,
                showExtensions: true,
                showCommonExtensions: true,
                persistAuthorization: true
            });
        };
    </script>
</body>
</html>"""
        return HandlerResult(
            status_code=200,
            content_type="text/html; charset=utf-8",
            body=swagger_html.encode("utf-8"),
        )

    def _get_postman_collection(self) -> HandlerResult:
        """Get Postman collection for API testing.

        Returns downloadable Postman Collection v2.1 format JSON file
        with all API endpoints organized by category.

        Returns:
            HandlerResult with Postman collection JSON
        """
        try:
            from aragora.server.openapi import handle_postman_request

            content, content_type = handle_postman_request()
            return HandlerResult(
                status_code=200,
                content_type=content_type,
                body=content.encode("utf-8"),
                headers={
                    "Content-Disposition": "attachment; filename=aragora.postman_collection.json"
                },
            )
        except (ImportError, ValueError, TypeError, KeyError, RuntimeError, OSError) as e:
            logger.error("Error generating Postman collection: %s", e)
            return error_response(safe_error_message(e, "Postman export"), 500)

    def _get_redoc(self) -> HandlerResult:
        """Serve ReDoc API documentation viewer.

        ReDoc provides an alternative, read-focused API documentation
        interface. Uses the same OpenAPI spec as Swagger UI.

        Returns:
            HandlerResult with ReDoc HTML page
        """
        redoc_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Aragora API - ReDoc</title>
    <link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,700|Roboto:300,400,700" rel="stylesheet">
    <style>
        body { margin: 0; padding: 0; }
    </style>
</head>
<body>
    <redoc spec-url="/api/v1/openapi.json"
           expand-responses="200,201"
           hide-download-button="false"
           native-scrollbars="true"
           path-in-middle-panel="true">
    </redoc>
    <script src="https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js"></script>
</body>
</html>"""
        return HandlerResult(
            status_code=200,
            content_type="text/html; charset=utf-8",
            body=redoc_html.encode("utf-8"),
        )
