"""
Compliance Report Download Handler.

Provides endpoints for generating and downloading compliance reports:
- POST /api/v1/compliance/reports/generate  (generate for framework+scope)
- GET  /api/v1/compliance/reports/:id        (retrieve report)
- GET  /api/v1/compliance/reports/:id/download?format=json|html|markdown  (download)
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from aragora.server.handlers.utils.decorators import require_permission
from aragora.server.handlers.utils.responses import HandlerResult as HR

logger = logging.getLogger(__name__)

# In-memory report cache (production would use a persistent store)
_report_cache: dict[str, Any] = {}

_VALID_DOWNLOAD_FORMATS = {"json", "html", "markdown"}


class ComplianceReportHandler(BaseHandler):
    """Handler for compliance report generation and download."""

    def __init__(self, ctx: dict[str, Any] | None = None, **kwargs: Any):
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        return path.startswith("/api/v1/compliance/reports")

    @handle_errors("get compliance report")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        if not path.startswith("/api/v1/compliance/reports"):
            return None

        # GET /api/v1/compliance/reports/:id/download
        if path.endswith("/download"):
            return self._handle_download(path, query_params)

        # GET /api/v1/compliance/reports/:id
        parts = path.strip("/").split("/")
        if len(parts) == 5:  # api/v1/compliance/reports/{id}
            report_id = parts[4]
            return self._handle_get_report(report_id)

        return None

    @require_permission("compliance:generate")
    @handle_errors("generate compliance report")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        if path != "/api/v1/compliance/reports/generate":
            return None

        body, error = self.read_json_object_or_error(handler)
        if error:
            return error
        if body is None:
            return error_response("JSON object body is required", 400)

        framework = body.get("framework", "general")
        debate_id = body.get("debate_id")
        scope = body.get("scope", {})

        if not isinstance(debate_id, str) or not debate_id.strip():
            return error_response("debate_id is required", 400)
        if not isinstance(framework, str):
            return error_response("framework must be a string", 400)
        if not isinstance(scope, dict):
            return error_response("scope must be a JSON object", 400)

        valid_frameworks = {"soc2", "gdpr", "hipaa", "iso27001", "general", "custom"}
        if framework not in valid_frameworks:
            return error_response(
                f"Invalid framework '{framework}'. Must be one of: {', '.join(sorted(valid_frameworks))}",
                400,
            )

        try:
            from aragora.compliance.report_generator import (
                ComplianceFramework,
                ComplianceReportGenerator,
            )

            framework_enum = ComplianceFramework(framework)
            generator = ComplianceReportGenerator()

            # Get debate result from storage
            storage = self.ctx.get("storage")
            debate_data = None
            if storage:
                debate_data = storage.get_debate(debate_id.strip())

            if debate_data is None:
                return error_response(f"Debate '{debate_id}' not found", 404)

            # Build a minimal DebateResult for the generator
            from aragora.core import DebateResult

            debate_result = DebateResult(
                task=debate_data.get("task", ""),
                consensus_reached=debate_data.get("consensus_reached", False),
                rounds_used=debate_data.get("rounds_used", 0),
                winner=debate_data.get("winner"),
                final_answer=debate_data.get("final_answer", ""),
            )

            report = generator.generate(
                debate_result=debate_result,
                debate_id=debate_id.strip(),
                framework=framework_enum,
                include_evidence=scope.get("include_evidence", True),
                include_chain=scope.get("include_chain", True),
                include_full_transcript=scope.get("include_transcript", False),
            )

            # Cache the report
            _report_cache[report.report_id] = report

            return json_response(
                {
                    "report_id": report.report_id,
                    "debate_id": report.debate_id,
                    "framework": report.framework.value,
                    "generated_at": report.generated_at.isoformat(),
                    "summary": report.summary,
                },
                status=201,
            )

        except ImportError:
            return error_response("Compliance report generator not available", 503)
        except (ValueError, TypeError) as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request", 400)

    def _handle_get_report(self, report_id: str) -> HandlerResult:
        """Retrieve a generated report."""
        report = _report_cache.get(report_id)
        if report is None:
            return error_response(f"Report '{report_id}' not found", 404)

        return json_response(report.to_dict())

    def _handle_download(self, path: str, query_params: dict[str, Any]) -> HandlerResult:
        """Download a report in the requested format."""
        parts = path.strip("/").split("/")
        if len(parts) < 5:
            return error_response("Invalid path", 400)
        report_id = parts[4]

        report = _report_cache.get(report_id)
        if report is None:
            return error_response(f"Report '{report_id}' not found", 404)

        fmt = query_params.get("format", "json")
        if fmt not in _VALID_DOWNLOAD_FORMATS:
            return error_response(
                f"Invalid format '{fmt}'. Must be one of: {', '.join(sorted(_VALID_DOWNLOAD_FORMATS))}",
                400,
            )

        try:
            from aragora.compliance.report_generator import ComplianceReportGenerator

            generator = ComplianceReportGenerator()

            if fmt == "json":
                content = generator.export_json(report)
                return HR(
                    status_code=200,
                    content_type="application/json",
                    body=content.encode("utf-8"),
                    headers={
                        "Content-Disposition": f'attachment; filename="report-{report_id}.json"'
                    },
                )
            elif fmt == "markdown":
                content = generator.export_markdown(report)
                return HR(
                    status_code=200,
                    content_type="text/markdown; charset=utf-8",
                    body=content.encode("utf-8"),
                    headers={
                        "Content-Disposition": f'attachment; filename="report-{report_id}.md"'
                    },
                )
            elif fmt == "html":
                # Use markdown export wrapped in basic HTML
                md_content = generator.export_markdown(report)
                html = f"<html><head><title>Report {report_id}</title></head><body><pre>{md_content}</pre></body></html>"
                return HR(
                    status_code=200,
                    content_type="text/html; charset=utf-8",
                    body=html.encode("utf-8"),
                    headers={
                        "Content-Disposition": f'attachment; filename="report-{report_id}.html"'
                    },
                )
        except ImportError:
            return error_response("Report generator not available", 503)

        return error_response("Export failed", 500)


__all__ = ["ComplianceReportHandler", "_report_cache"]
