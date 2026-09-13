"""
Differentiation Dashboard Handler.

Aggregates data from existing subsystems to demonstrate Aragora's unique
value propositions: adversarial vetting, calibrated trust, and institutional memory.

Endpoints:
    GET /api/v1/differentiation/summary      - Top-level differentiation metrics
    GET /api/v1/differentiation/vetting       - Adversarial vetting evidence
    GET /api/v1/differentiation/calibration   - Multi-agent calibration advantage
    GET /api/v1/differentiation/memory        - Institutional memory growth
    GET /api/v1/differentiation/benchmarks    - Industry benchmark comparison
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.server.versioning.compat import strip_version_prefix

try:
    from aragora.rbac.decorators import require_permission
except ImportError:  # pragma: no cover

    def require_permission(*_a, **_kw):  # type: ignore[misc]
        def _noop(fn):  # type: ignore[no-untyped-def]
            return fn

        return _noop


from ..base import (
    BaseHandler,
    HandlerResult,
    handle_errors,
    json_response,
)

logger = logging.getLogger(__name__)


class DifferentiationHandler(BaseHandler):
    """Handler for differentiation dashboard endpoints."""

    ROUTES = [
        "/api/differentiation/summary",
        "/api/differentiation/vetting",
        "/api/differentiation/calibration",
        "/api/differentiation/memory",
        "/api/differentiation/benchmarks",
    ]

    def __init__(self, ctx: dict | None = None):
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        normalized = strip_version_prefix(path)
        return normalized in self.ROUTES

    @require_permission("analytics:read")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route GET requests."""
        normalized = strip_version_prefix(path)

        if normalized == "/api/differentiation/summary":
            return self._get_summary(query_params)
        if normalized == "/api/differentiation/vetting":
            return self._get_vetting(query_params)
        if normalized == "/api/differentiation/calibration":
            return self._get_calibration(query_params)
        if normalized == "/api/differentiation/memory":
            return self._get_memory(query_params)
        if normalized == "/api/differentiation/benchmarks":
            return self._get_benchmarks(query_params)

        return None

    @handle_errors("get differentiation summary")
    def _get_summary(self, query_params: dict[str, Any]) -> HandlerResult:
        """Top-level metrics showing Aragora's differentiation."""
        receipt_store = self._get_receipt_store()
        elo_system = self._get_elo_system()

        # Debate quality metrics from receipts
        receipts = receipt_store.list_receipts(limit=100) if receipt_store else []
        total_decisions = len(receipts)

        # Count receipts with dissenting views preserved
        dissent_count = sum(1 for r in receipts if getattr(r, "dissenting_views", None))

        # Average robustness score
        robustness_scores = [
            getattr(r, "robustness_score", 0.0)
            for r in receipts
            if getattr(r, "robustness_score", None) is not None
        ]
        avg_robustness = (
            sum(robustness_scores) / len(robustness_scores) if robustness_scores else 0.0
        )

        # Calibration from ELO
        calibration_data: dict[str, Any] = {}
        if elo_system:
            try:
                cal = getattr(elo_system, "get_calibration_stats", None)
                if callable(cal):
                    calibration_data = cal() or {}
            except (AttributeError, TypeError):
                pass

        avg_ece = calibration_data.get("avg_ece", 0.0)

        # Agent diversity (number of distinct agents used)
        agent_count = 0
        if elo_system:
            try:
                ratings = getattr(elo_system, "get_all_ratings", None)
                if callable(ratings):
                    agent_count = len(ratings() or {})
            except (AttributeError, TypeError):
                pass

        return json_response(
            {
                "data": {
                    "total_decisions": total_decisions,
                    "dissent_preserved_rate": (
                        dissent_count / total_decisions if total_decisions > 0 else 0.0
                    ),
                    "avg_robustness_score": round(avg_robustness, 3),
                    "avg_calibration_error": round(avg_ece, 4),
                    "active_agent_count": agent_count,
                    "adversarial_vetting_enabled": True,
                    "multi_model_consensus": agent_count >= 3,
                }
            }
        )

    @handle_errors("get vetting evidence")
    def _get_vetting(self, query_params: dict[str, Any]) -> HandlerResult:
        """Adversarial vetting evidence from decision receipts."""
        receipt_store = self._get_receipt_store()
        limit = min(int(query_params.get("limit", "20")), 50)
        receipts = receipt_store.list_receipts(limit=limit) if receipt_store else []

        vetting_evidence: list[dict[str, Any]] = []
        for r in receipts:
            receipt_id = getattr(r, "id", None) or getattr(r, "receipt_id", "")
            dissenting = getattr(r, "dissenting_views", []) or []
            tensions = getattr(r, "unresolved_tensions", []) or []
            verified = getattr(r, "verified_claims", []) or []
            robustness = getattr(r, "robustness_score", None)
            question = getattr(r, "question", "") or getattr(r, "topic", "")

            vetting_evidence.append(
                {
                    "receipt_id": str(receipt_id),
                    "question": str(question)[:200],
                    "dissenting_views_count": len(dissenting),
                    "unresolved_tensions_count": len(tensions),
                    "verified_claims_count": len(verified),
                    "robustness_score": robustness,
                    "has_adversarial_challenge": len(dissenting) > 0 or len(tensions) > 0,
                }
            )

        # Aggregates
        total = len(vetting_evidence)
        adversarially_vetted = sum(1 for v in vetting_evidence if v["has_adversarial_challenge"])

        return json_response(
            {
                "data": {
                    "evidence": vetting_evidence,
                    "aggregates": {
                        "total_decisions": total,
                        "adversarially_vetted": adversarially_vetted,
                        "adversarial_rate": adversarially_vetted / total if total > 0 else 0.0,
                        "avg_dissenting_views": (
                            sum(v["dissenting_views_count"] for v in vetting_evidence) / total
                            if total > 0
                            else 0.0
                        ),
                        "avg_verified_claims": (
                            sum(v["verified_claims_count"] for v in vetting_evidence) / total
                            if total > 0
                            else 0.0
                        ),
                    },
                }
            }
        )

    @handle_errors("get calibration data")
    def _get_calibration(self, query_params: dict[str, Any]) -> HandlerResult:
        """Multi-agent calibration advantage data."""
        elo_system = self._get_elo_system()

        agents = []
        if elo_system:
            try:
                ratings = getattr(elo_system, "get_all_ratings", None)
                if callable(ratings):
                    all_ratings = ratings() or {}
                    for agent_id, rating_data in all_ratings.items():
                        if isinstance(rating_data, dict):
                            elo = rating_data.get("elo", 1500)
                            wins = rating_data.get("wins", 0)
                            losses = rating_data.get("losses", 0)
                        else:
                            elo = getattr(rating_data, "elo", 1500)
                            wins = getattr(rating_data, "wins", 0)
                            losses = getattr(rating_data, "losses", 0)

                        total_games = wins + losses
                        win_rate = wins / total_games if total_games > 0 else 0.5

                        agents.append(
                            {
                                "agent_id": agent_id,
                                "elo": round(elo, 1),
                                "win_rate": round(win_rate, 3),
                                "games_played": total_games,
                            }
                        )
            except (AttributeError, TypeError):
                pass

        agents.sort(key=lambda a: a["elo"], reverse=True)

        # Compute ensemble calibration (consensus of multiple agents is better calibrated)
        single_best_elo = agents[0]["elo"] if agents else 1500
        ensemble_avg_elo = sum(a["elo"] for a in agents) / len(agents) if agents else 1500

        return json_response(
            {
                "data": {
                    "agents": agents[:20],
                    "ensemble_metrics": {
                        "agent_count": len(agents),
                        "best_single_elo": round(single_best_elo, 1),
                        "ensemble_avg_elo": round(ensemble_avg_elo, 1),
                        "elo_spread": round(
                            (agents[0]["elo"] - agents[-1]["elo"]) if len(agents) >= 2 else 0, 1
                        ),
                        "diversity_score": min(1.0, len(agents) / 10.0),
                    },
                }
            }
        )

    @handle_errors("get memory data")
    def _get_memory(self, query_params: dict[str, Any]) -> HandlerResult:
        """Institutional memory growth metrics."""
        memory_stats: dict[str, Any] = {}

        # Try to get memory stats from context
        try:
            from aragora.memory.continuum import ContinuumMemory

            memory = self.ctx.get("continuum_memory")
            if memory and isinstance(memory, ContinuumMemory):
                stats_fn = getattr(memory, "get_stats", None)
                if callable(stats_fn):
                    memory_stats = stats_fn() or {}
        except (ImportError, AttributeError):
            pass

        # Try KnowledgeMound stats
        km_stats: dict[str, Any] = {}
        try:
            km = self.ctx.get("knowledge_mound")
            if km:
                km_stats_fn = getattr(km, "get_stats", None)
                if callable(km_stats_fn):
                    km_stats = km_stats_fn() or {}
        except (ImportError, AttributeError):
            pass

        return json_response(
            {
                "data": {
                    "memory": {
                        "total_entries": memory_stats.get("total_entries", 0),
                        "fast_tier": memory_stats.get("fast_count", 0),
                        "medium_tier": memory_stats.get("medium_count", 0),
                        "slow_tier": memory_stats.get("slow_count", 0),
                        "glacial_tier": memory_stats.get("glacial_count", 0),
                    },
                    "knowledge_mound": {
                        "total_artifacts": km_stats.get("total_artifacts", 0),
                        "adapter_count": km_stats.get("adapter_count", 34),
                        "cross_debate_links": km_stats.get("cross_debate_links", 0),
                    },
                    "learning_indicators": {
                        "decisions_informing_future": memory_stats.get("reuse_count", 0),
                        "knowledge_reuse_rate": memory_stats.get("reuse_rate", 0.0),
                        "memory_quality_score": memory_stats.get("quality_score", 0.0),
                    },
                }
            }
        )

    @handle_errors("get benchmark comparison")
    def _get_benchmarks(self, query_params: dict[str, Any]) -> HandlerResult:
        """Industry benchmark comparison."""
        category = query_params.get("category", "technology")

        try:
            from aragora.analytics.benchmarking import BenchmarkAggregator

            aggregator = self.ctx.get("benchmark_aggregator")
            if aggregator is None:
                aggregator = BenchmarkAggregator()
                self.ctx["benchmark_aggregator"] = aggregator

            benchmarks = aggregator.compute_benchmarks(category)
            items = [b.to_dict() for b in benchmarks] if benchmarks else []
        except (ImportError, AttributeError):
            items = []

        return json_response(
            {
                "data": {
                    "category": category,
                    "benchmarks": items,
                    "available_categories": [
                        "healthcare",
                        "financial",
                        "legal",
                        "technology",
                    ],
                }
            }
        )

    def _get_receipt_store(self) -> Any:
        """Get receipt store from context."""
        store = self.ctx.get("receipt_store")
        if store is None:
            try:
                from aragora.gauntlet.receipts import ReceiptStore

                store = ReceiptStore()
                self.ctx["receipt_store"] = store
            except (ImportError, AttributeError):
                pass
        return store

    def _get_elo_system(self) -> Any:
        """Get ELO system from context."""
        elo = self.ctx.get("elo_system")
        if elo is None:
            try:
                from aragora.ranking.elo import EloSystem

                elo = EloSystem()
                self.ctx["elo_system"] = elo
            except (ImportError, AttributeError):
                pass
        return elo
