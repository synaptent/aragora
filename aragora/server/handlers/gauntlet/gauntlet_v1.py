"""
Gauntlet API v1 - Versioned, OpenAPI-compliant endpoints.

Provides stable, documented API endpoints for Gauntlet functionality:
- GET /api/v1/gauntlet/schema/{type} - Get JSON schemas
- GET /api/v1/gauntlet/templates - List audit templates
- GET /api/v1/gauntlet/templates/{id} - Get specific template
- POST /api/v1/gauntlet/{id}/export - Export receipt in various formats
- GET /api/v1/gauntlet/{id}/heatmap/export - Export heatmap

All endpoints follow RFC 7807 for error responses.
"""

from __future__ import annotations

import json
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from ..base import (
    HandlerResult,
    get_string_param,
    json_response,
)
from ..secure import SecureHandler
from ..utils.auth import ForbiddenError, UnauthorizedError, get_auth_context

logger = logging.getLogger(__name__)


@runtime_checkable
class VersionedAPIHandler(Protocol):
    """Protocol for versioned API handlers with body/path_params dispatch."""

    def get_path_pattern(self) -> str:
        """Return the URL path pattern for this handler."""
        ...

    def get_methods(self) -> list[str]:
        """Return the HTTP methods this handler supports."""
        ...

    async def handle(
        self,
        body: dict[str, Any] | None,
        path_params: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> HandlerResult:
        """Handle the request."""
        ...


class GauntletSecureHandler(ABC):
    """Base handler for Gauntlet v1 endpoints with RBAC protection.

    This is an ABC that implements the VersionedAPIHandler protocol,
    which has a different dispatch pattern than BaseHandler.
    It uses composition to access SecureHandler security features.
    """

    RESOURCE_TYPE = "gauntlet"

    def __init__(self, server_context: dict[str, Any]) -> None:
        """Initialize with server context."""
        self.ctx = server_context
        # Create a SecureHandler instance for security method access
        self._secure_handler = SecureHandler(server_context)

    @abstractmethod
    def get_path_pattern(self) -> str:
        """Return the URL path pattern for this handler. Override in subclasses."""
        ...

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the given path.

        Uses get_path_pattern() to determine the base path prefix.
        """
        try:
            pattern = self.get_path_pattern()
        except Exception:
            return False
        return path.startswith(pattern.split("{")[0].rstrip("/") or pattern)

    def get_methods(self) -> list[str]:
        """Return the HTTP methods this handler supports. Default is GET."""
        return ["GET"]

    @abstractmethod
    async def handle(
        self,
        body: dict[str, Any] | None,
        path_params: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> HandlerResult:
        """Handle the request. Override in subclasses."""
        ...

    async def get_auth_context(self, request: Any, require_auth: bool = True) -> Any:
        """Get authentication context for the current request."""
        return await get_auth_context(request, require_auth=require_auth)

    def check_permission(
        self,
        auth_context: Any,
        permission: str,
        resource_id: str | None = None,
    ) -> bool:
        """Check if user has a specific permission."""
        return self._secure_handler.check_permission(auth_context, permission, resource_id)

    async def check_gauntlet_permission(
        self,
        kwargs: dict[str, Any],
        permission: str = "gauntlet.read",
    ) -> HandlerResult | None:
        """Check permission and return error response if denied."""
        try:
            handler = kwargs.get("handler")
            auth_context = await self.get_auth_context(handler, require_auth=True)
            self.check_permission(auth_context, permission)
            return None  # Permission granted
        except UnauthorizedError:
            return rfc7807_error(
                status=401,
                title="Unauthorized",
                detail="Authentication required",
                problem_type=f"{PROBLEM_TYPE_BASE}/unauthorized",
            )
        except ForbiddenError as e:
            logger.warning("Gauntlet permission denied: %s", e)
            return rfc7807_error(
                status=403,
                title="Forbidden",
                detail="Insufficient permissions for this operation",
                problem_type=f"{PROBLEM_TYPE_BASE}/forbidden",
            )


# RFC 7807 Problem Types
PROBLEM_TYPE_BASE = "https://aragora.ai/problems"
PROBLEM_NOT_FOUND = f"{PROBLEM_TYPE_BASE}/not-found"
PROBLEM_VALIDATION = f"{PROBLEM_TYPE_BASE}/validation-error"
PROBLEM_INTERNAL = f"{PROBLEM_TYPE_BASE}/internal-error"


def rfc7807_error(
    status: int,
    title: str,
    detail: str,
    problem_type: str = PROBLEM_INTERNAL,
    instance: str | None = None,
    **extra: Any,
) -> HandlerResult:
    """Create an RFC 7807 Problem Details response."""
    problem = {
        "type": problem_type,
        "title": title,
        "status": status,
        "detail": detail,
    }
    if instance:
        problem["instance"] = instance
    problem.update(extra)
    return HandlerResult(
        status_code=status,
        content_type="application/problem+json",
        body=json.dumps(problem).encode("utf-8"),
    )


class GauntletSchemaHandler(GauntletSecureHandler):
    """
    GET /api/v1/gauntlet/schema/{type}

    Returns JSON Schema for the specified type.

    Path Parameters:
        type: Schema type (decision-receipt, risk-heatmap, problem-detail)

    Returns:
        JSON Schema document
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        super().__init__(ctx or {})

    def get_path_pattern(self) -> str:
        return r"/api/v1/gauntlet/schema/(?P<schema_type>[a-z-]+)"

    async def handle(
        self,
        body: dict[str, Any] | None,
        path_params: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> HandlerResult:
        # RBAC check
        if error := await self.check_gauntlet_permission(kwargs, "gauntlet.read"):
            return error

        try:
            schema_type = path_params.get("schema_type") if path_params else None

            if not schema_type:
                return rfc7807_error(
                    status=400,
                    title="Missing Schema Type",
                    detail="Schema type is required in the path",
                    problem_type=PROBLEM_VALIDATION,
                )

            from aragora.gauntlet.api import get_all_schemas

            schemas = get_all_schemas()

            if schema_type not in schemas:
                available = list(schemas.keys())
                return rfc7807_error(
                    status=404,
                    title="Schema Not Found",
                    detail=f"Schema type '{schema_type}' not found. Available: {available}",
                    problem_type=PROBLEM_NOT_FOUND,
                    available_schemas=available,
                )

            schema = schemas[schema_type]
            return json_response(schema)

        except (ImportError, KeyError, ValueError, AttributeError) as e:
            logger.exception("Error getting schema: %s", e)
            return rfc7807_error(
                status=500,
                title="Internal Server Error",
                detail="Failed to retrieve schema",
            )


class GauntletAllSchemasHandler(GauntletSecureHandler):
    """
    GET /api/v1/gauntlet/schemas

    Returns all available JSON Schemas.

    Returns:
        Object mapping schema names to their definitions
    """

    def get_path_pattern(self) -> str:
        return r"/api/v1/gauntlet/schemas"

    async def handle(
        self,
        body: dict[str, Any] | None,
        path_params: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> HandlerResult:
        # RBAC check
        if error := await self.check_gauntlet_permission(kwargs, "gauntlet.read"):
            return error

        try:
            from aragora.gauntlet.api import get_all_schemas, SCHEMA_VERSION

            schemas = get_all_schemas()

            response = {
                "version": SCHEMA_VERSION,
                "schemas": schemas,
                "count": len(schemas),
            }

            return json_response(response)

        except (ImportError, KeyError, ValueError, AttributeError) as e:
            logger.exception("Error getting schemas: %s", e)
            return rfc7807_error(
                status=500,
                title="Internal Server Error",
                detail="Failed to retrieve schemas",
            )


class GauntletTemplatesListHandler(GauntletSecureHandler):
    """
    GET /api/v1/gauntlet/templates

    List all available audit templates.

    Query Parameters:
        category: Filter by category (compliance, security, legal, financial, operational)

    Returns:
        List of available templates with metadata
    """

    def get_path_pattern(self) -> str:
        return r"/api/v1/gauntlet/templates"

    async def handle(
        self,
        body: dict[str, Any] | None,
        path_params: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> HandlerResult:
        # RBAC check
        if error := await self.check_gauntlet_permission(kwargs, "gauntlet.read"):
            return error

        try:
            from aragora.gauntlet.api import list_templates, TemplateCategory

            category_str = get_string_param(query_params, "category")
            category = None

            if category_str:
                try:
                    category = TemplateCategory(category_str.lower())
                except ValueError:
                    valid_categories = [c.value for c in TemplateCategory]
                    return rfc7807_error(
                        status=400,
                        title="Invalid Category",
                        detail=f"Category must be one of: {valid_categories}",
                        problem_type=PROBLEM_VALIDATION,
                        valid_categories=valid_categories,
                    )

            templates = list_templates(category)

            response = {
                "templates": [
                    {
                        "id": t.id,
                        "name": t.name,
                        "category": t.category.value,
                        "description": t.description,
                        "version": t.version,
                        "regulations": t.regulations,
                        "supported_formats": [f.value for f in t.supported_formats],
                    }
                    for t in templates
                ],
                "count": len(templates),
            }

            return json_response(response)

        except (ImportError, KeyError, ValueError, AttributeError) as e:
            logger.exception("Error listing templates: %s", e)
            return rfc7807_error(
                status=500,
                title="Internal Server Error",
                detail="Failed to list templates",
            )


class GauntletTemplateHandler(GauntletSecureHandler):
    """
    GET /api/v1/gauntlet/templates/{id}

    Get a specific audit template by ID.

    Path Parameters:
        id: Template identifier

    Returns:
        Full template definition
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        super().__init__(ctx or {})

    def get_path_pattern(self) -> str:
        return r"/api/v1/gauntlet/templates/(?P<template_id>[a-z0-9-]+)"

    async def handle(
        self,
        body: dict[str, Any] | None,
        path_params: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> HandlerResult:
        # RBAC check
        if error := await self.check_gauntlet_permission(kwargs, "gauntlet.read"):
            return error

        try:
            template_id = path_params.get("template_id") if path_params else None

            if not template_id:
                return rfc7807_error(
                    status=400,
                    title="Missing Template ID",
                    detail="Template ID is required in the path",
                    problem_type=PROBLEM_VALIDATION,
                )

            from aragora.gauntlet.api import get_template, list_templates

            template = get_template(template_id)

            if not template:
                available = [t.id for t in list_templates()]
                return rfc7807_error(
                    status=404,
                    title="Template Not Found",
                    detail=f"Template '{template_id}' not found. Available: {available}",
                    problem_type=PROBLEM_NOT_FOUND,
                    available_templates=available,
                )

            return json_response(template.to_dict())

        except (ImportError, KeyError, ValueError, AttributeError) as e:
            logger.exception("Error getting template: %s", e)
            return rfc7807_error(
                status=500,
                title="Internal Server Error",
                detail="Failed to retrieve template",
            )


class GauntletReceiptExportHandler(GauntletSecureHandler):
    """
    POST /api/v1/gauntlet/{id}/export

    Export a decision receipt in the specified format.

    Path Parameters:
        id: Gauntlet run ID

    Body:
        format: Export format (json, markdown, html, csv, sarif)
        template_id: Optional audit template to apply
        options: Export options (include_provenance, include_config, etc.)

    Returns:
        Exported content with appropriate Content-Type
    """

    def get_path_pattern(self) -> str:
        return r"/api/v1/gauntlet/(?P<gauntlet_id>[a-zA-Z0-9-]+)/export"

    def get_methods(self) -> list[str]:
        return ["POST"]

    async def handle(
        self,
        body: dict[str, Any] | None,
        path_params: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> HandlerResult:
        # RBAC check - export is a read operation
        if error := await self.check_gauntlet_permission(kwargs, "gauntlet.read"):
            return error

        try:
            gauntlet_id = path_params.get("gauntlet_id") if path_params else None

            if not gauntlet_id:
                return rfc7807_error(
                    status=400,
                    title="Missing Gauntlet ID",
                    detail="Gauntlet ID is required in the path",
                    problem_type=PROBLEM_VALIDATION,
                )

            # Parse request body
            body = body or {}
            format_str = body.get("format", "json").lower()
            template_id = body.get("template_id")
            options_dict = body.get("options", {})

            # Get the receipt
            from aragora.server.handlers.gauntlet import _gauntlet_runs, _get_storage

            # Try in-memory first
            run = _gauntlet_runs.get(gauntlet_id)

            # Try persistent storage
            if not run:
                storage = _get_storage()
                if hasattr(storage, "get_result"):
                    run = storage.get_result(gauntlet_id)

            if not run:
                return rfc7807_error(
                    status=404,
                    title="Gauntlet Not Found",
                    detail=f"Gauntlet run '{gauntlet_id}' not found",
                    problem_type=PROBLEM_NOT_FOUND,
                    instance=f"/api/v1/gauntlet/{gauntlet_id}",
                )

            # Check status
            status = run.get("status")
            if status != "completed":
                return rfc7807_error(
                    status=400,
                    title="Gauntlet Not Complete",
                    detail=f"Gauntlet run is '{status}', export requires 'completed' status",
                    problem_type=PROBLEM_VALIDATION,
                    current_status=status,
                )

            # Get or create receipt
            receipt = run.get("receipt")
            if not receipt:
                # Try to create receipt from result
                result = run.get("result")
                if result:
                    if hasattr(result, "to_receipt"):
                        receipt = result.to_receipt()
                    else:
                        # Result is a dict, need to reconstruct
                        from aragora.gauntlet.receipt import DecisionReceipt as DR

                        receipt = DR(
                            receipt_id=str(uuid.uuid4()),
                            gauntlet_id=gauntlet_id,
                            timestamp=result.get("completed_at", datetime.now().isoformat()),
                            input_summary=result.get("input_summary", ""),
                            input_hash=result.get("input_hash", ""),
                            risk_summary=result.get("risk_summary", {}),
                            attacks_attempted=result.get("attack_summary", {}).get(
                                "total_attacks", 0
                            ),
                            attacks_successful=result.get("attack_summary", {}).get(
                                "successful_attacks", 0
                            ),
                            probes_run=result.get("probe_summary", {}).get("probes_run", 0),
                            vulnerabilities_found=result.get("risk_summary", {}).get("total", 0),
                            verdict=result.get("verdict", "FAIL"),
                            confidence=result.get("confidence", 0.0),
                            robustness_score=result.get("robustness_score", 0.0),
                        )

            if not receipt:
                return rfc7807_error(
                    status=500,
                    title="Receipt Generation Failed",
                    detail="Could not generate receipt from gauntlet result",
                )

            # Apply template if specified
            if template_id:
                from aragora.gauntlet.api import get_template, TemplateFormat

                template = get_template(template_id)
                if not template:
                    return rfc7807_error(
                        status=404,
                        title="Template Not Found",
                        detail=f"Template '{template_id}' not found",
                        problem_type=PROBLEM_NOT_FOUND,
                    )

                # Map format to template format
                format_map = {
                    "markdown": TemplateFormat.MARKDOWN,
                    "html": TemplateFormat.HTML,
                    "json": TemplateFormat.JSON,
                    "text": TemplateFormat.TEXT,
                }
                template_format = format_map.get(format_str, TemplateFormat.MARKDOWN)

                # Render with template
                content = template.render(receipt, template_format)
                content_type = {
                    "markdown": "text/markdown",
                    "html": "text/html",
                    "json": "application/json",
                    "text": "text/plain",
                }.get(format_str, "text/plain")

                content_bytes = content.encode("utf-8") if isinstance(content, str) else content
                return HandlerResult(
                    status_code=200,
                    content_type=content_type,
                    body=content_bytes,
                )

            # Export without template
            from aragora.gauntlet.api import (
                ReceiptExportFormat,
                ExportOptions,
                export_receipt,
            )

            # Map format string to enum
            export_format_map: dict[str, ReceiptExportFormat] = {
                "json": ReceiptExportFormat.JSON,
                "markdown": ReceiptExportFormat.MARKDOWN,
                "html": ReceiptExportFormat.HTML,
                "csv": ReceiptExportFormat.CSV,
                "sarif": ReceiptExportFormat.SARIF,
            }

            if format_str not in export_format_map:
                valid_formats = list(export_format_map.keys())
                return rfc7807_error(
                    status=400,
                    title="Invalid Format",
                    detail=f"Format must be one of: {valid_formats}",
                    problem_type=PROBLEM_VALIDATION,
                    valid_formats=valid_formats,
                )

            export_format = export_format_map[format_str]

            # Create export options
            options = ExportOptions(
                include_provenance=options_dict.get("include_provenance", True),
                include_config=options_dict.get("include_config", False),
                max_vulnerabilities=options_dict.get("max_vulnerabilities", 100),
                validate_schema=options_dict.get("validate_schema", False),
            )

            exported = export_receipt(receipt, export_format, options)
            content_bytes = exported.encode("utf-8") if isinstance(exported, str) else exported

            # Set appropriate content type
            content_type = {
                "json": "application/json",
                "markdown": "text/markdown",
                "html": "text/html",
                "csv": "text/csv",
                "sarif": "application/sarif+json",
                "pdf": "application/pdf",
            }.get(format_str, "application/json")

            return HandlerResult(
                status_code=200,
                content_type=content_type,
                body=content_bytes,
            )

        except (ImportError, KeyError, ValueError, TypeError, AttributeError) as e:
            logger.exception("Error exporting receipt: %s", e)
            return rfc7807_error(
                status=500,
                title="Export Failed",
                detail="Receipt export failed",
            )


class GauntletHeatmapExportHandler(GauntletSecureHandler):
    """
    GET /api/v1/gauntlet/{id}/heatmap/export

    Export a risk heatmap in the specified format.

    Path Parameters:
        id: Gauntlet run ID

    Query Parameters:
        format: Export format (json, csv, svg, ascii, html)

    Returns:
        Exported heatmap content
    """

    def get_path_pattern(self) -> str:
        return r"/api/v1/gauntlet/(?P<gauntlet_id>[a-zA-Z0-9-]+)/heatmap/export"

    async def handle(
        self,
        body: dict[str, Any] | None,
        path_params: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> HandlerResult:
        # RBAC check
        if error := await self.check_gauntlet_permission(kwargs, "gauntlet.read"):
            return error

        try:
            gauntlet_id = path_params.get("gauntlet_id") if path_params else None

            if not gauntlet_id:
                return rfc7807_error(
                    status=400,
                    title="Missing Gauntlet ID",
                    detail="Gauntlet ID is required in the path",
                    problem_type=PROBLEM_VALIDATION,
                )

            format_str = get_string_param(query_params, "format", "json").lower()

            # Get the gauntlet run
            from aragora.server.handlers.gauntlet import _gauntlet_runs, _get_storage

            run = _gauntlet_runs.get(gauntlet_id)
            if not run:
                storage = _get_storage()
                if hasattr(storage, "get_result"):
                    run = storage.get_result(gauntlet_id)

            if not run:
                return rfc7807_error(
                    status=404,
                    title="Gauntlet Not Found",
                    detail=f"Gauntlet run '{gauntlet_id}' not found",
                    problem_type=PROBLEM_NOT_FOUND,
                )

            # Get heatmap
            heatmap = run.get("heatmap")
            if not heatmap:
                result = run.get("result")
                if result and hasattr(result, "to_heatmap"):
                    heatmap = result.to_heatmap()

            if not heatmap:
                return rfc7807_error(
                    status=404,
                    title="Heatmap Not Available",
                    detail="No heatmap data available for this gauntlet run",
                    problem_type=PROBLEM_NOT_FOUND,
                )

            # Export
            from aragora.gauntlet.api import HeatmapExportFormat, export_heatmap

            format_map: dict[str, HeatmapExportFormat] = {
                "json": HeatmapExportFormat.JSON,
                "csv": HeatmapExportFormat.CSV,
                "svg": HeatmapExportFormat.SVG,
                "ascii": HeatmapExportFormat.ASCII,
                "html": HeatmapExportFormat.HTML,
            }

            if format_str not in format_map:
                valid_formats = list(format_map.keys())
                return rfc7807_error(
                    status=400,
                    title="Invalid Format",
                    detail=f"Format must be one of: {valid_formats}",
                    problem_type=PROBLEM_VALIDATION,
                    valid_formats=valid_formats,
                )

            export_format = format_map[format_str]
            exported = export_heatmap(heatmap, export_format)
            content_bytes = exported.encode("utf-8") if isinstance(exported, str) else exported

            content_type = {
                "json": "application/json",
                "csv": "text/csv",
                "svg": "image/svg+xml",
                "ascii": "text/plain",
                "html": "text/html",
            }.get(format_str, "application/json")

            return HandlerResult(
                status_code=200,
                content_type=content_type,
                body=content_bytes,
            )

        except (ImportError, KeyError, ValueError, TypeError, AttributeError) as e:
            logger.exception("Error exporting heatmap: %s", e)
            return rfc7807_error(
                status=500,
                title="Export Failed",
                detail="Heatmap export failed",
            )


class GauntletValidateReceiptHandler(GauntletSecureHandler):
    """
    POST /api/v1/gauntlet/validate/receipt

    Validate a decision receipt against the JSON schema.

    Body:
        Receipt JSON to validate

    Returns:
        Validation result with any errors
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        super().__init__(ctx or {})

    def get_path_pattern(self) -> str:
        return r"/api/v1/gauntlet/validate/receipt"

    def get_methods(self) -> list[str]:
        return ["POST"]

    async def handle(
        self,
        body: dict[str, Any] | None,
        path_params: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> HandlerResult:
        # RBAC check - validation is a read operation
        if error := await self.check_gauntlet_permission(kwargs, "gauntlet.read"):
            return error

        try:
            if not body:
                return rfc7807_error(
                    status=400,
                    title="Missing Body",
                    detail="Request body with receipt data is required",
                    problem_type=PROBLEM_VALIDATION,
                )

            from aragora.gauntlet.api import validate_receipt

            is_valid, errors = validate_receipt(body)

            response = {
                "valid": is_valid,
                "errors": errors if errors else [],
                "error_count": len(errors),
            }

            return json_response(response)

        except (ImportError, KeyError, ValueError, TypeError) as e:
            logger.exception("Error validating receipt: %s", e)
            return rfc7807_error(
                status=500,
                title="Validation Failed",
                detail="Receipt validation failed",
            )


# Handler classes for registration
# These are concrete implementations of GauntletSecureHandler
GAUNTLET_V1_HANDLERS: list[type[GauntletSecureHandler]] = [
    GauntletSchemaHandler,
    GauntletAllSchemasHandler,
    GauntletTemplatesListHandler,
    GauntletTemplateHandler,
    GauntletReceiptExportHandler,
    GauntletHeatmapExportHandler,
    GauntletValidateReceiptHandler,
]


def register_gauntlet_v1_handlers(router: Any, server_context: Any = None) -> None:
    """Register all v1 Gauntlet handlers with a router."""
    ctx = server_context or {}
    for handler_cls in GAUNTLET_V1_HANDLERS:
        handler = handler_cls(ctx)
        router.add_handler(handler)
