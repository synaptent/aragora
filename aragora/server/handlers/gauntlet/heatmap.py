"""
Heatmap handling methods for gauntlet stress-tests.

This module contains:
- _get_heatmap: Get risk heatmap for a gauntlet run
"""

from __future__ import annotations

import logging

from aragora.rbac.decorators import require_permission
from aragora.tenancy.record_scope import OrgScope, record_not_found

from ..base import HandlerResult, error_response, get_string_param, json_response
from ..openapi_decorator import api_endpoint
from .storage import get_owned_run


def _get_storage_proxy():
    """Resolve storage accessor dynamically for test patching."""
    from . import _get_storage as get_storage

    return get_storage()


logger = logging.getLogger(__name__)


class GauntletHeatmapMixin:
    """Mixin providing gauntlet heatmap methods."""

    @api_endpoint(
        method="GET",
        path="/api/v1/gauntlet/{gauntlet_id}/heatmap",
        summary="Get risk heatmap",
        description="Get the risk heatmap visualization for a completed gauntlet run.",
        tags=["Gauntlet"],
        parameters=[
            {"name": "gauntlet_id", "in": "path", "required": True, "schema": {"type": "string"}},
            {
                "name": "format",
                "in": "query",
                "schema": {"type": "string", "enum": ["json", "svg", "ascii"]},
            },
        ],
        responses={
            "200": {"description": "Risk heatmap in requested format"},
            "400": {"description": "Gauntlet not completed"},
            "401": {"description": "Authentication required"},
            "404": {"description": "Gauntlet run not found"},
        },
    )
    @require_permission("gauntlet:read")
    async def _get_heatmap(
        self, gauntlet_id: str, query_params: dict, *, scope: OrgScope
    ) -> HandlerResult:
        """Get risk heatmap for one of the caller org's gauntlet runs."""
        from aragora.gauntlet.heatmap import HeatmapCell, RiskHeatmap

        result = None
        result_obj = None

        # Check in-memory first
        run = get_owned_run(gauntlet_id, scope)
        if run is not None:
            if run["status"] != "completed":
                return error_response("Gauntlet run not completed", 400)
            result = run["result"]
            result_obj = run.get("result_obj")
        else:
            # Check persistent storage
            try:
                storage = _get_storage_proxy()
                stored = storage.get(gauntlet_id, scope.org_id)
                if stored:
                    result = stored
                else:
                    return record_not_found("Gauntlet run")
            except (OSError, RuntimeError, ValueError) as e:
                logger.warning("Storage lookup failed for %s: %s", gauntlet_id, e)
                return record_not_found("Gauntlet run")

        # Generate heatmap
        if result_obj:
            heatmap = RiskHeatmap.from_mode_result(result_obj)
        else:
            # COMPATIBILITY: Use vulnerabilities if findings not present (post-restart scenario)
            findings_data = result.get("findings") or result.get("vulnerabilities", [])

            cells = []
            categories = set()
            severities = ["critical", "high", "medium", "low"]

            for finding in findings_data:
                category = finding.get("category", "unknown")
                categories.add(category)

            category_severity_counts: dict[tuple[str, str], int] = {}
            for finding in findings_data:
                category = finding.get("category", "unknown")
                severity = finding.get("severity_level", "medium").lower()
                key = (category, severity)
                category_severity_counts[key] = category_severity_counts.get(key, 0) + 1

            for category in sorted(categories):
                for severity in severities:
                    count = category_severity_counts.get((category, severity), 0)
                    cells.append(
                        HeatmapCell(
                            category=category,
                            severity=severity,
                            count=count,
                        )
                    )

            heatmap = RiskHeatmap(
                cells=cells,
                categories=sorted(list(categories)),
                severities=severities,
                total_findings=result.get("total_findings", 0),
            )

        # Return format based on query param
        format_type = get_string_param(query_params, "format", "json")

        if format_type == "svg":
            return HandlerResult(
                status_code=200,
                content_type="image/svg+xml",
                body=heatmap.to_svg().encode("utf-8"),
            )
        elif format_type == "ascii":
            return HandlerResult(
                status_code=200,
                content_type="text/plain",
                body=heatmap.to_ascii().encode("utf-8"),
            )
        else:
            return json_response(heatmap.to_dict())
