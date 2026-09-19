"""
Results handling methods for gauntlet stress-tests.

This module contains:
- _list_results: List recent gauntlet results with pagination
- _compare_results: Compare two gauntlet results
- _delete_result: Delete a gauntlet result
- _get_status: Get gauntlet run status
- _list_personas: List available personas
"""

from __future__ import annotations

import html
import logging
from datetime import datetime
from typing import Any

from aragora.rbac.decorators import require_permission

from ..base import (
    HandlerResult,
    error_response,
    get_int_param,
    get_string_param,
    json_response,
    safe_error_message,
)
from ..openapi_decorator import api_endpoint
from .storage import _STORAGE_ERRORS, get_gauntlet_runs, resolve_gauntlet_run


def _get_storage_proxy():
    """Resolve storage accessor dynamically for test patching."""
    from . import _get_storage as get_storage

    return get_storage()


logger = logging.getLogger(__name__)


class GauntletResultsMixin:
    """Mixin providing gauntlet results methods."""

    @api_endpoint(
        method="GET",
        path="/api/v1/gauntlet/personas",
        summary="List available personas",
        description="List all available regulatory personas for gauntlet stress-testing.",
        tags=["Gauntlet"],
        responses={
            "200": {"description": "List of available personas"},
            "401": {"description": "Authentication required"},
        },
    )
    @require_permission("gauntlet:read")
    def _list_personas(self) -> HandlerResult:
        """List available regulatory personas."""
        try:
            from aragora.gauntlet.personas import get_persona, list_personas

            personas_list = []
            for name in list_personas():
                persona = get_persona(name)
                personas_list.append(
                    {
                        "id": name,
                        "name": persona.name,
                        "description": persona.description,
                        "regulation": persona.regulation,
                        "attack_count": len(persona.attack_prompts),
                        "categories": list(set(a.category for a in persona.attack_prompts)),
                    }
                )

            return json_response(
                {
                    "personas": personas_list,
                    "count": len(personas_list),
                }
            )
        except ImportError:
            return json_response(
                {
                    "personas": [],
                    "count": 0,
                    "error": "Personas module not available",
                }
            )

    @api_endpoint(
        method="GET",
        path="/api/v1/gauntlet/{gauntlet_id}",
        summary="Get gauntlet status",
        description="Get the status and results of a gauntlet stress-test run.",
        tags=["Gauntlet"],
        parameters=[
            {"name": "gauntlet_id", "in": "path", "required": True, "schema": {"type": "string"}}
        ],
        responses={
            "200": {
                "description": "Gauntlet status and results",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "gauntlet_id": {"type": "string"},
                                "status": {"type": "string"},
                                "result": {"type": "object"},
                                "error": {"type": "string"},
                            },
                        }
                    }
                },
            },
            "401": {"description": "Authentication required"},
            "404": {"description": "Gauntlet run not found"},
        },
    )
    @require_permission("gauntlet:read")
    async def _get_status(self, gauntlet_id: str) -> HandlerResult:
        """Get gauntlet run status."""
        gauntlet_runs = get_gauntlet_runs()

        try:
            run = await resolve_gauntlet_run(
                gauntlet_id, gauntlet_runs.get(gauntlet_id), _get_storage_proxy
            )
            if run:
                return json_response({k: v for k, v in run.items() if k != "result_obj"})
        except _STORAGE_ERRORS as e:
            logger.warning("Storage lookup failed for %s: %s", gauntlet_id, e)
            from aragora.gauntlet.errors import gauntlet_error_response

            body, status = gauntlet_error_response(
                "storage_error", {"reason": "Storage lookup failed"}
            )
            return json_response(body, status=status)

        return error_response(f"Gauntlet run not found: {gauntlet_id}", 404)

    @api_endpoint(
        method="GET",
        path="/api/v1/gauntlet/results",
        summary="List gauntlet results",
        description="List recent gauntlet stress-test results with pagination and filtering.",
        tags=["Gauntlet"],
        parameters=[
            {
                "name": "limit",
                "in": "query",
                "schema": {"type": "integer", "default": 20, "maximum": 100},
            },
            {"name": "offset", "in": "query", "schema": {"type": "integer", "default": 0}},
            {"name": "verdict", "in": "query", "schema": {"type": "string"}},
            {"name": "min_severity", "in": "query", "schema": {"type": "string"}},
        ],
        responses={
            "200": {"description": "Paginated list of gauntlet results"},
            "401": {"description": "Authentication required"},
            "500": {"description": "Storage error"},
        },
    )
    @require_permission("gauntlet:read")
    def _list_results(self, query_params: dict) -> HandlerResult:
        """List recent gauntlet results with pagination."""
        try:
            storage = _get_storage_proxy()

            limit = get_int_param(query_params, "limit", 20)
            offset = get_int_param(query_params, "offset", 0)
            verdict = get_string_param(query_params, "verdict", None)
            min_severity = get_string_param(query_params, "min_severity", None)

            # Clamp values
            limit = min(max(limit, 1), 100)
            offset = max(offset, 0)

            results = storage.list_recent(
                limit=limit,
                offset=offset,
                verdict=verdict,
                min_severity=min_severity,
            )

            total = storage.count(verdict=verdict)

            return json_response(
                {
                    "results": [
                        {
                            "gauntlet_id": r.gauntlet_id,
                            "input_hash": r.input_hash,
                            "input_summary": (
                                r.input_summary[:100] + "..."
                                if len(r.input_summary) > 100
                                else r.input_summary
                            ),
                            "verdict": r.verdict,
                            "confidence": r.confidence,
                            "robustness_score": r.robustness_score,
                            "critical_count": r.critical_count,
                            "high_count": r.high_count,
                            "total_findings": r.total_findings,
                            "created_at": r.created_at.isoformat(),
                            "duration_seconds": r.duration_seconds,
                        }
                        for r in results
                    ],
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                }
            )
        except (OSError, RuntimeError, ValueError, TypeError) as e:
            logger.error("Failed to list results: %s", e)
            return error_response(safe_error_message(e, "list results"), 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/gauntlet/{gauntlet_id}/compare/{compare_id}",
        summary="Compare gauntlet results",
        description="Compare two gauntlet stress-test runs to analyze differences.",
        tags=["Gauntlet"],
        parameters=[
            {"name": "gauntlet_id", "in": "path", "required": True, "schema": {"type": "string"}},
            {"name": "compare_id", "in": "path", "required": True, "schema": {"type": "string"}},
        ],
        responses={
            "200": {"description": "Comparison results"},
            "401": {"description": "Authentication required"},
            "404": {"description": "One or both gauntlet runs not found"},
            "500": {"description": "Comparison failed"},
        },
    )
    @require_permission("gauntlet:compare")
    def _compare_results(self, id1: str, id2: str, query_params: dict) -> HandlerResult:
        """Compare two gauntlet results."""
        try:
            storage = _get_storage_proxy()
            comparison = storage.compare(id1, id2)

            if comparison is None:
                return error_response("One or both gauntlet runs not found", 404)

            return json_response(comparison)
        except (OSError, RuntimeError, ValueError, TypeError) as e:
            logger.error("Failed to compare results: %s", e)
            return error_response(safe_error_message(e, "compare results"), 500)

    @api_endpoint(
        method="DELETE",
        path="/api/v1/gauntlet/{gauntlet_id}",
        summary="Delete gauntlet result",
        description="Delete a gauntlet stress-test result from storage.",
        tags=["Gauntlet"],
        parameters=[
            {"name": "gauntlet_id", "in": "path", "required": True, "schema": {"type": "string"}}
        ],
        responses={
            "200": {"description": "Gauntlet result deleted"},
            "401": {"description": "Authentication required"},
            "404": {"description": "Gauntlet run not found"},
            "500": {"description": "Delete failed"},
        },
    )
    @require_permission("gauntlet:delete")
    def _delete_result(self, gauntlet_id: str, query_params: dict) -> HandlerResult:
        """Delete a gauntlet result."""
        gauntlet_runs = get_gauntlet_runs()

        try:
            # Remove from in-memory if present
            if gauntlet_id in gauntlet_runs:
                del gauntlet_runs[gauntlet_id]

            # Remove from persistent storage
            storage = _get_storage_proxy()
            deleted = storage.delete(gauntlet_id)

            if deleted:
                return json_response({"deleted": True, "gauntlet_id": gauntlet_id})
            else:
                return error_response(f"Gauntlet run not found: {gauntlet_id}", 404)
        except (OSError, RuntimeError, ValueError, KeyError) as e:
            logger.error("Failed to delete result: %s", e)
            return error_response(safe_error_message(e, "delete result"), 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/gauntlet/{gauntlet_id}/export",
        summary="Export gauntlet report",
        description="Export a comprehensive gauntlet report with findings, heatmap, and summary.",
        tags=["Gauntlet"],
        parameters=[
            {"name": "gauntlet_id", "in": "path", "required": True, "schema": {"type": "string"}},
            {
                "name": "format",
                "in": "query",
                "schema": {"type": "string", "enum": ["json", "html", "full_html"]},
            },
            {
                "name": "include_heatmap",
                "in": "query",
                "schema": {"type": "string", "default": "true"},
            },
            {
                "name": "include_findings",
                "in": "query",
                "schema": {"type": "string", "default": "true"},
            },
        ],
        responses={
            "200": {"description": "Comprehensive report in requested format"},
            "400": {"description": "Gauntlet not completed or unsupported format"},
            "401": {"description": "Authentication required"},
            "404": {"description": "Gauntlet run not found"},
        },
    )
    @require_permission("gauntlet:export")
    async def _export_report(
        self,
        gauntlet_id: str,
        query_params: dict,
        handler: Any = None,
    ) -> HandlerResult:
        """Export a comprehensive gauntlet report.

        Query params:
        - format: json (default), html, full_html (includes CSS)
        - include_heatmap: true/false (default true)
        - include_findings: true/false (default true)
        """
        gauntlet_runs = get_gauntlet_runs()

        # Get result
        run = None
        result = None
        _result_obj = None  # GauntletResult object for enhanced report (in-memory only)

        if gauntlet_id in gauntlet_runs:
            run = gauntlet_runs[gauntlet_id]
            if run["status"] != "completed":
                return error_response("Gauntlet run not completed", 400)
            result = run["result"]
            _result_obj = run.get("result_obj")
        else:
            try:
                storage = _get_storage_proxy()
                stored = storage.get(gauntlet_id)
                if stored:
                    result = stored
                else:
                    return error_response(f"Gauntlet run not found: {gauntlet_id}", 404)
            except (OSError, RuntimeError, ValueError) as e:
                logger.warning("Storage lookup failed for %s: %s", gauntlet_id, e)
                return error_response(f"Gauntlet run not found: {gauntlet_id}", 404)

        # Parse options
        format_type = get_string_param(query_params, "format", "json")
        include_heatmap = get_string_param(query_params, "include_heatmap", "true") == "true"
        include_findings = get_string_param(query_params, "include_findings", "true") == "true"

        # Build comprehensive report
        report: dict[str, Any] = {
            "gauntlet_id": gauntlet_id,
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "verdict": result.get("verdict", "UNKNOWN"),
                "confidence": result.get("confidence", 0),
                "robustness_score": result.get("robustness_score", 0),
                "risk_score": result.get("risk_score", 0),
                "coverage_score": result.get("coverage_score", 0),
            },
            "findings_summary": {
                "total": result.get("total_findings", 0),
                "critical": result.get("critical_count", 0),
                "high": result.get("high_count", 0),
                "medium": result.get("medium_count", 0),
                "low": result.get("low_count", 0),
            },
            "input": {
                "summary": run.get("input_summary", "") if run else result.get("input_summary", ""),
                "type": run.get("input_type", "") if run else result.get("input_type", ""),
                "hash": run.get("input_hash", "") if run else result.get("input_hash", ""),
            },
            "timing": {
                "created_at": run.get("created_at", "") if run else "",
                "completed_at": run.get("completed_at", "") if run else "",
            },
        }

        if include_findings:
            # COMPATIBILITY: GauntletResult stores "vulnerabilities", but API expects "findings"
            # Map vulnerabilities to findings for backwards compatibility
            findings = result.get("findings") or result.get("vulnerabilities", [])
            report["findings"] = findings

        if include_heatmap:
            # Generate heatmap data
            # COMPATIBILITY: Use vulnerabilities if findings not present (post-restart scenario)
            findings_for_heatmap = result.get("findings") or result.get("vulnerabilities", [])

            cells = []
            categories = set()
            severities = ["critical", "high", "medium", "low"]

            for finding in findings_for_heatmap:
                category = finding.get("category", "unknown")
                categories.add(category)

            category_severity_counts: dict[tuple[str, str], int] = {}
            # COMPATIBILITY: Use findings_for_heatmap (includes vulnerabilities fallback)
            for finding in findings_for_heatmap:
                category = finding.get("category", "unknown")
                severity = finding.get("severity_level", finding.get("severity", "medium")).lower()
                key = (category, severity)
                category_severity_counts[key] = category_severity_counts.get(key, 0) + 1

            for category in sorted(categories):
                for severity in severities:
                    count = category_severity_counts.get((category, severity), 0)
                    cells.append({"category": category, "severity": severity, "count": count})

            report["heatmap"] = {
                "cells": cells,
                "categories": sorted(list(categories)),
                "severities": severities,
            }

        # Enhanced report data from GauntletResult object (in-memory runs only)
        if _result_obj is not None:
            enhanced: dict[str, Any] = {}
            if hasattr(_result_obj, "verdict_reasoning") and _result_obj.verdict_reasoning:
                enhanced["verdict_reasoning"] = _result_obj.verdict_reasoning
            if hasattr(_result_obj, "attack_summary"):
                enhanced["attack_summary"] = (
                    _result_obj.attack_summary.__dict__
                    if hasattr(_result_obj.attack_summary, "__dict__")
                    else str(_result_obj.attack_summary)
                )
            if hasattr(_result_obj, "probe_summary"):
                enhanced["probe_summary"] = (
                    _result_obj.probe_summary.__dict__
                    if hasattr(_result_obj.probe_summary, "__dict__")
                    else str(_result_obj.probe_summary)
                )
            if hasattr(_result_obj, "scenario_summary"):
                enhanced["scenario_summary"] = (
                    _result_obj.scenario_summary.__dict__
                    if hasattr(_result_obj.scenario_summary, "__dict__")
                    else str(_result_obj.scenario_summary)
                )
            if enhanced:
                report["enhanced"] = enhanced

        if format_type == "json":
            return json_response(report)

        elif format_type == "html" or format_type == "full_html":
            # Generate HTML report
            # Escape user-controlled data to prevent XSS attacks
            verdict_raw = report["summary"]["verdict"]
            verdict = html.escape(str(verdict_raw))
            safe_gauntlet_id = html.escape(str(gauntlet_id)[:12])
            verdict_color = (
                "#22c55e"
                if verdict_raw in ["APPROVED", "PASS"]
                else "#ef4444"
                if verdict_raw in ["REJECTED", "FAIL"]
                else "#eab308"
            )

            html_parts = [
                f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Gauntlet Report - {safe_gauntlet_id}</title>
    <style>
        :root {{ --bg: #0a0a0a; --surface: #1a1a1a; --border: #333; --text: #e0e0e0; --muted: #888; --green: #22c55e; --red: #ef4444; --yellow: #eab308; --cyan: #06b6d4; }}
        body {{ font-family: ui-monospace, monospace; background: var(--bg); color: var(--text); margin: 0; padding: 2rem; line-height: 1.6; }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        .header {{ border-bottom: 2px solid {verdict_color}; padding-bottom: 1rem; margin-bottom: 2rem; }}
        .verdict {{ font-size: 2rem; color: {verdict_color}; margin: 0; }}
        .id {{ color: var(--muted); font-size: 0.75rem; }}
        .card {{ background: var(--surface); border: 1px solid var(--border); padding: 1rem; margin-bottom: 1rem; border-radius: 4px; }}
        .card-title {{ color: var(--cyan); font-size: 0.75rem; text-transform: uppercase; margin-bottom: 0.5rem; }}
        .stat {{ display: inline-block; margin-right: 2rem; }}
        .stat-value {{ font-size: 1.5rem; }}
        .stat-label {{ color: var(--muted); font-size: 0.75rem; }}
        .finding {{ border-left: 3px solid; padding: 0.5rem 1rem; margin: 0.5rem 0; }}
        .finding.critical {{ border-color: var(--red); background: rgba(239,68,68,0.1); }}
        .finding.high {{ border-color: #f97316; background: rgba(249,115,22,0.1); }}
        .finding.medium {{ border-color: var(--yellow); background: rgba(234,179,8,0.1); }}
        .finding.low {{ border-color: var(--cyan); background: rgba(6,182,212,0.1); }}
        .badge {{ display: inline-block; padding: 0.25rem 0.5rem; font-size: 0.7rem; border-radius: 2px; }}
        .badge.critical {{ background: var(--red); color: white; }}
        .badge.high {{ background: #f97316; color: white; }}
        .badge.medium {{ background: var(--yellow); color: black; }}
        .badge.low {{ background: var(--cyan); color: black; }}
        .heatmap {{ display: grid; gap: 2px; margin-top: 1rem; }}
        .heatmap-cell {{ padding: 0.5rem; text-align: center; font-size: 0.75rem; }}
        .footer {{ margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--border); color: var(--muted); font-size: 0.75rem; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 class="verdict">{verdict}</h1>
            <div class="id">Gauntlet ID: {safe_gauntlet_id}</div>
            <div class="id">Generated: {html.escape(str(report.get("generated_at", "")))}</div>
        </div>

        <div class="card">
            <div class="card-title">Summary</div>
            <div class="stat">
                <div class="stat-value" style="color: {verdict_color}">{(report["summary"]["confidence"] * 100):.0f}%</div>
                <div class="stat-label">Confidence</div>
            </div>
            <div class="stat">
                <div class="stat-value" style="color: var(--cyan)">{(report["summary"]["robustness_score"] * 100):.0f}%</div>
                <div class="stat-label">Robustness</div>
            </div>
            <div class="stat">
                <div class="stat-value">{report["findings_summary"]["total"]}</div>
                <div class="stat-label">Total Findings</div>
            </div>
        </div>

        <div class="card">
            <div class="card-title">Findings Breakdown</div>
            <div class="stat">
                <div class="stat-value" style="color: var(--red)">{report["findings_summary"]["critical"]}</div>
                <div class="stat-label">Critical</div>
            </div>
            <div class="stat">
                <div class="stat-value" style="color: #f97316">{report["findings_summary"]["high"]}</div>
                <div class="stat-label">High</div>
            </div>
            <div class="stat">
                <div class="stat-value" style="color: var(--yellow)">{report["findings_summary"]["medium"]}</div>
                <div class="stat-label">Medium</div>
            </div>
            <div class="stat">
                <div class="stat-value" style="color: var(--cyan)">{report["findings_summary"]["low"]}</div>
                <div class="stat-label">Low</div>
            </div>
        </div>
""",
            ]

            if include_findings and report.get("findings"):
                html_parts.append("""
        <div class="card">
            <div class="card-title">Findings Detail</div>
""")
                for finding in report["findings"][:20]:  # Limit to 20 for HTML
                    # Escape all finding fields to prevent XSS attacks
                    severity = html.escape(finding.get("severity_level", "medium").lower())
                    title = html.escape(str(finding.get("title", "Unknown")))
                    description = html.escape(str(finding.get("description", ""))[:200])
                    html_parts.append(f"""
            <div class="finding {severity}">
                <span class="badge {severity}">{severity.upper()}</span>
                <strong>{title}</strong>
                <div style="color: var(--muted); font-size: 0.85rem;">{description}</div>
            </div>
""")
                html_parts.append("        </div>")

            # Escape generated_at to prevent XSS
            generated_at = html.escape(str(report.get("generated_at", "")))
            html_parts.append(f"""
        <div class="footer">
            Report generated by Aragora Gauntlet | {generated_at}
        </div>
    </div>
</body>
</html>
""")
            html_content = "".join(html_parts)

            return HandlerResult(
                status_code=200,
                content_type="text/html",
                body=html_content.encode("utf-8"),
            )

        else:
            return error_response(f"Unsupported format: {format_type}", 400)
