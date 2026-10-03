"""
Decision Benchmarking endpoint handler.

Provides REST APIs for anonymized decision-quality benchmarks:

- GET /api/v1/benchmarks            -- List benchmarks for a category
- GET /api/v1/benchmarks/categories -- List available benchmark categories
- GET /api/v1/benchmarks/compare    -- Compare tenant metrics against benchmarks
"""

from __future__ import annotations

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
from ..utils.decorators import require_permission

logger = logging.getLogger(__name__)


class BenchmarkingHandler(BaseHandler):
    """Handler for decision benchmarking endpoints."""

    ROUTES = [
        "/api/benchmarks",
        "/api/benchmarks/categories",
        "/api/benchmarks/compare",
    ]

    def __init__(self, ctx: dict | None = None):
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        normalized = strip_version_prefix(path)
        return normalized in self.ROUTES

    @require_permission("benchmarks:read")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route GET requests."""
        normalized = strip_version_prefix(path)

        if normalized == "/api/benchmarks/categories":
            return self._get_categories()
        if normalized == "/api/benchmarks/compare":
            return self._get_compare(query_params)
        if normalized == "/api/benchmarks":
            return self._get_benchmarks(query_params)

        return None

    @handle_errors("get benchmarks")
    def _get_benchmarks(self, query_params: dict[str, Any]) -> HandlerResult:
        """GET /api/v1/benchmarks -- list aggregated benchmarks for a category.

        Query params:
            category (required): Benchmark category (e.g. "healthcare", "1-5", "vendor").
        """
        category = query_params.get("category", "")

        if not category:
            return error_response(
                "Missing required query parameter: category",
                400,
            )

        aggregator = self._get_aggregator()
        benchmarks = aggregator.compute_benchmarks(category)

        items = [b.to_dict() for b in benchmarks]

        return json_response({"benchmarks": items, "count": len(items)})

    @handle_errors("get benchmark categories")
    def _get_categories(self) -> HandlerResult:
        """GET /api/v1/benchmarks/categories -- list available benchmark categories."""
        aggregator = self._get_aggregator()
        categories = aggregator.get_categories()
        return json_response({"categories": categories, "count": len(categories)})

    @handle_errors("compare benchmarks")
    def _get_compare(self, query_params: dict[str, Any]) -> HandlerResult:
        """GET /api/v1/benchmarks/compare -- compare tenant metrics to benchmarks.

        Query params:
            category (required): Benchmark category to compare against.
            tenant_id: Optional tenant identifier (for audit logging).
            consensus_rate, confidence_avg, time_to_decision,
            cost_per_decision, calibration_score: Metric values to compare.
        """
        category = query_params.get("category", "")

        if not category:
            return error_response(
                "Missing required query parameter: category",
                400,
            )

        from aragora.analytics.benchmarking import BENCHMARK_METRICS

        tenant_metrics: dict[str, float] = {}
        for metric in BENCHMARK_METRICS:
            raw = query_params.get(metric)
            if raw is not None:
                try:
                    tenant_metrics[metric] = float(raw)
                except (ValueError, TypeError):
                    return error_response(
                        f"Invalid value for {metric}: must be a number",
                        400,
                    )

        if not tenant_metrics:
            return error_response(
                "At least one metric must be provided for comparison",
                400,
            )

        aggregator = self._get_aggregator()
        comparison = aggregator.compare(tenant_metrics, category)

        return json_response(
            {
                "comparison": comparison,
                "category": category,
                "tenant_id": query_params.get("tenant_id"),
            }
        )

    def _get_aggregator(self) -> Any:
        """Get or create the BenchmarkAggregator from server context."""
        aggregator = self.ctx.get("benchmark_aggregator")
        if aggregator is None:
            from aragora.analytics.benchmarking import BenchmarkAggregator

            aggregator = BenchmarkAggregator()
            self.ctx["benchmark_aggregator"] = aggregator
        return aggregator
