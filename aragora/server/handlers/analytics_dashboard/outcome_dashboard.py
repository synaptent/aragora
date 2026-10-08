"""
Decision Outcome Dashboard API Handler.

Provides a consolidated endpoint for the outcome analytics dashboard
(GitHub issue #281) that combines:
- Decision quality scores and trends
- Agent performance with ELO ratings and Brier calibration scores
- Consensus quality metrics (agreement rates, convergence speed)
- Calibration curve data (predicted vs actual confidence accuracy)

Endpoints:
- GET /api/v1/outcome-dashboard          - Full dashboard data
- GET /api/v1/outcome-dashboard/quality  - Decision quality score + trend
- GET /api/v1/outcome-dashboard/agents   - Agent leaderboard (ELO + Brier)
- GET /api/v1/outcome-dashboard/history  - Decision history with scores
- GET /api/v1/outcome-dashboard/calibration - Calibration curve data
"""

from __future__ import annotations

import logging
from typing import Any

from ..base import (
    error_response,
    handle_errors,
    json_response,
)
from ..utils.responses import HandlerResult
from ..secure import SecureHandler
from ..utils.decorators import require_permission
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter: 60 requests per minute
_dashboard_limiter = RateLimiter(requests_per_minute=60)

# Standard exception tuple for error handlers
_SAFE_EXCEPTIONS = (
    ValueError,
    KeyError,
    TypeError,
    AttributeError,
    RuntimeError,
    OSError,
    ImportError,
)


def _get_outcome_analytics() -> Any:
    """Lazy import of OutcomeAnalytics to avoid heavy startup cost."""
    from aragora.analytics.outcome_analytics import get_outcome_analytics

    return get_outcome_analytics()


def _get_debate_analytics() -> Any:
    """Lazy import of DebateAnalytics."""
    from aragora.analytics.debate_analytics import get_debate_analytics

    return get_debate_analytics()


def _parse_period(period: str):
    """Lazy import _parse_period."""
    from aragora.analytics.outcome_analytics import _parse_period as _pp

    return _pp(period)


class OutcomeDashboardHandler(SecureHandler):
    """Handler for the consolidated outcome analytics dashboard.

    Combines decision outcome data, agent ELO ratings, calibration scores,
    and convergence metrics into dashboard-ready payloads.
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    RESOURCE_TYPE = "outcome_dashboard"

    ROUTES = [
        "/api/v1/outcome-dashboard",
        "/api/v1/outcome-dashboard/quality",
        "/api/v1/outcome-dashboard/agents",
        "/api/v1/outcome-dashboard/history",
        "/api/v1/outcome-dashboard/calibration",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        return path in self.ROUTES

    @require_permission("analytics:read")
    def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
        method: str = "GET",
    ) -> HandlerResult | None:
        """Route outcome dashboard requests to appropriate methods."""
        client_ip = get_client_ip(handler)
        if not _dashboard_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for outcome dashboard: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        if method != "GET":
            return error_response("Method not allowed", 405)

        if path == "/api/v1/outcome-dashboard":
            return self._get_full_dashboard(query_params)
        elif path == "/api/v1/outcome-dashboard/quality":
            return self._get_quality_score(query_params)
        elif path == "/api/v1/outcome-dashboard/agents":
            return self._get_agent_leaderboard(query_params)
        elif path == "/api/v1/outcome-dashboard/history":
            return self._get_decision_history(query_params)
        elif path == "/api/v1/outcome-dashboard/calibration":
            return self._get_calibration_curve(query_params)

        return None

    # =========================================================================
    # GET /api/v1/outcome-dashboard — Full dashboard data
    # =========================================================================

    @handle_errors("get outcome dashboard")
    async def _get_full_dashboard(self, query_params: dict[str, Any]) -> HandlerResult:
        """Return the full outcome dashboard payload."""
        period = query_params.get("period", "30d")

        quality = await self._build_quality_score(period)
        agents = await self._build_agent_leaderboard(period)
        history = await self._build_decision_history(period, limit=20)
        calibration = await self._build_calibration_curve(period)

        return json_response(
            {
                "data": {
                    "quality": quality,
                    "agents": agents,
                    "history": history,
                    "calibration": calibration,
                    "period": period,
                }
            }
        )

    # =========================================================================
    # GET /api/v1/outcome-dashboard/quality — Decision quality score
    # =========================================================================

    @handle_errors("get quality score")
    async def _get_quality_score(self, query_params: dict[str, Any]) -> HandlerResult:
        """Return decision quality score and trend."""
        period = query_params.get("period", "30d")
        quality = await self._build_quality_score(period)
        return json_response({"data": quality})

    # =========================================================================
    # GET /api/v1/outcome-dashboard/agents — Agent leaderboard
    # =========================================================================

    @handle_errors("get agent leaderboard")
    async def _get_agent_leaderboard(self, query_params: dict[str, Any]) -> HandlerResult:
        """Return agent performance leaderboard with ELO + calibration."""
        period = query_params.get("period", "30d")
        agents = await self._build_agent_leaderboard(period)
        return json_response({"data": agents})

    # =========================================================================
    # GET /api/v1/outcome-dashboard/history — Decision history
    # =========================================================================

    @handle_errors("get decision history")
    async def _get_decision_history(self, query_params: dict[str, Any]) -> HandlerResult:
        """Return paginated decision history with quality scores."""
        period = query_params.get("period", "30d")
        limit = min(int(query_params.get("limit", "50")), 200)
        offset = int(query_params.get("offset", "0"))
        history = await self._build_decision_history(period, limit=limit, offset=offset)
        return json_response({"data": history})

    # =========================================================================
    # GET /api/v1/outcome-dashboard/calibration — Calibration curve
    # =========================================================================

    @handle_errors("get calibration curve")
    async def _get_calibration_curve(self, query_params: dict[str, Any]) -> HandlerResult:
        """Return calibration curve data."""
        period = query_params.get("period", "30d")
        calibration = await self._build_calibration_curve(period)
        return json_response({"data": calibration})

    # =========================================================================
    # Internal builders
    # =========================================================================

    async def _build_quality_score(self, period: str) -> dict[str, Any]:
        """Build the decision quality score payload."""
        try:
            analytics = _get_outcome_analytics()
            consensus_rate = await analytics.get_consensus_rate(period=period)
            avg_rounds = await analytics.get_average_rounds(period=period)
            trend = await analytics.get_decision_quality_trend(period=period)

            delta = _parse_period(period)
            da = _get_debate_analytics()
            stats = await da.get_debate_stats(days_back=delta.days or 1)

            # Compute a composite quality score (0-100):
            # 40% consensus rate + 30% round efficiency + 30% completion rate
            round_efficiency = max(0.0, 1.0 - (avg_rounds / 20.0))
            completion_rate = (
                stats.completed_debates / stats.total_debates if stats.total_debates > 0 else 0.0
            )
            quality_score = (
                0.4 * consensus_rate + 0.3 * round_efficiency + 0.3 * completion_rate
            ) * 100

            # Compute previous period for comparison
            prev_quality = None
            try:
                # Simple trend indicator from trend data
                if len(trend) >= 2:
                    first_half = trend[: len(trend) // 2]
                    second_half = trend[len(trend) // 2 :]
                    first_avg = (
                        sum(p.consensus_rate for p in first_half) / len(first_half)
                        if first_half
                        else 0
                    )
                    second_avg = (
                        sum(p.consensus_rate for p in second_half) / len(second_half)
                        if second_half
                        else 0
                    )
                    change_pct = (
                        ((second_avg - first_avg) / first_avg * 100) if first_avg > 0 else 0.0
                    )
                    prev_quality = round(change_pct, 1)
            except _SAFE_EXCEPTIONS:
                pass

            return {
                "quality_score": round(quality_score, 1),
                "consensus_rate": round(consensus_rate, 4),
                "avg_rounds": round(avg_rounds, 2),
                "total_decisions": stats.total_debates,
                "completed_decisions": stats.completed_debates,
                "completion_rate": round(completion_rate, 4),
                "quality_change": prev_quality,
                "trend": [p.to_dict() for p in trend],
                "period": period,
            }
        except _SAFE_EXCEPTIONS as e:
            logger.warning("Failed to build quality score: %s", e)
            return {
                "quality_score": 0.0,
                "consensus_rate": 0.0,
                "avg_rounds": 0.0,
                "total_decisions": 0,
                "completed_decisions": 0,
                "completion_rate": 0.0,
                "quality_change": None,
                "trend": [],
                "period": period,
            }

    async def _build_agent_leaderboard(self, period: str) -> dict[str, Any]:
        """Build agent leaderboard with ELO and calibration data."""
        try:
            delta = _parse_period(period)
            da = _get_debate_analytics()
            leaderboard = await da.get_agent_leaderboard(
                limit=20, days_back=delta.days or 1, sort_by="elo"
            )

            # Get calibration data if available
            calibration_map: dict[str, dict[str, Any]] = {}
            try:
                from aragora.ranking.elo import EloSystem

                elo_sys = EloSystem()
                cal_lb: list[Any] = elo_sys.get_calibration_leaderboard(limit=50)
                for entry in cal_lb:
                    agent_name = entry.agent_name
                    if agent_name:
                        calibration_map[agent_name] = {
                            "brier_score": entry.calibration_brier_score,
                            "accuracy": entry.calibration_accuracy,
                            "count": entry.calibration_total,
                        }
            except _SAFE_EXCEPTIONS as e:
                logger.debug("Calibration data unavailable: %s", e)

            agents = []
            for agent in leaderboard:
                cal_data = calibration_map.get(agent.agent_name, {})
                agents.append(
                    {
                        "rank": agent.rank,
                        "agent_id": agent.agent_id,
                        "agent_name": agent.agent_name,
                        "provider": agent.provider,
                        "model": agent.model,
                        "elo": round(agent.current_elo, 1),
                        "elo_change": round(agent.elo_change_period, 1),
                        "debates": agent.debates_participated,
                        "messages": agent.messages_sent,
                        "win_rate": round(agent.vote_ratio * 100, 1),
                        "error_rate": round(agent.error_rate * 100, 2),
                        "avg_response_ms": round(agent.avg_response_time_ms, 0),
                        "consensus_contributions": agent.consensus_contributions,
                        "brier_score": cal_data.get("brier_score"),
                        "calibration_accuracy": cal_data.get("accuracy"),
                        "calibration_count": cal_data.get("count", 0),
                    }
                )

            return {
                "agents": agents,
                "count": len(agents),
                "period": period,
            }
        except _SAFE_EXCEPTIONS as e:
            logger.warning("Failed to build agent leaderboard: %s", e)
            return {
                "agents": [],
                "count": 0,
                "period": period,
            }

    async def _build_decision_history(
        self, period: str, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """Build paginated decision history with quality scores."""
        try:
            delta = _parse_period(period)
            da = _get_debate_analytics()

            import json as _json
            import sqlite3
            from datetime import datetime, timezone

            decisions: list[dict[str, Any]] = []
            total_count = 0
            period_start = datetime.now(timezone.utc) - delta

            try:
                with sqlite3.connect(da.db_path) as conn:
                    conn.row_factory = sqlite3.Row

                    count_row = conn.execute(
                        "SELECT COUNT(*) as cnt FROM debate_records WHERE created_at >= ?",
                        (period_start.isoformat(),),
                    ).fetchone()
                    total_count = count_row["cnt"] if count_row else 0

                    cursor = conn.execute(
                        """
                        SELECT debate_id, status, rounds, consensus_reached,
                               duration_seconds, agents, protocol, total_cost,
                               total_messages, total_votes, created_at
                        FROM debate_records
                        WHERE created_at >= ?
                        ORDER BY created_at DESC
                        LIMIT ? OFFSET ?
                        """,
                        (period_start.isoformat(), limit, offset),
                    )
                    for row in cursor.fetchall():
                        agents = _json.loads(row["agents"]) if row["agents"] else []
                        rounds_val = row["rounds"] or 0
                        consensus = bool(row["consensus_reached"])
                        duration = row["duration_seconds"] or 0.0

                        # Per-debate quality score
                        round_eff = max(0.0, 1.0 - (rounds_val / 20.0))
                        debate_quality = (
                            0.5 * (1.0 if consensus else 0.0)
                            + 0.3 * round_eff
                            + 0.2 * (1.0 if row["status"] == "completed" else 0.0)
                        ) * 100

                        decisions.append(
                            {
                                "debate_id": row["debate_id"],
                                "task": row["protocol"] or "",
                                "status": row["status"],
                                "consensus_reached": consensus,
                                "quality_score": round(debate_quality, 1),
                                "rounds": rounds_val,
                                "agents": agents,
                                "agent_count": len(agents),
                                "duration_seconds": round(duration, 2),
                                "total_messages": row["total_messages"] or 0,
                                "total_votes": row["total_votes"] or 0,
                                "cost": row["total_cost"] or "0",
                                "created_at": row["created_at"] or "",
                            }
                        )
            except (sqlite3.Error, OSError, _json.JSONDecodeError) as e:
                logger.warning("Failed to query debate records: %s", e)

            return {
                "decisions": decisions,
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "period": period,
            }
        except _SAFE_EXCEPTIONS as e:
            logger.warning("Failed to build decision history: %s", e)
            return {
                "decisions": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
                "period": period,
            }

    async def _build_calibration_curve(self, period: str) -> dict[str, Any]:
        """Build calibration curve data (predicted vs actual confidence)."""
        try:
            delta = _parse_period(period)
            da = _get_debate_analytics()

            import sqlite3
            from datetime import datetime, timezone

            # Build calibration buckets from debate outcomes
            # Bucket confidence predictions (from consensus_reached / rounds)
            # and compare to actual outcomes
            buckets: dict[str, dict[str, Any]] = {}
            bucket_boundaries = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
            period_start = datetime.now(timezone.utc) - delta

            for i in range(len(bucket_boundaries) - 1):
                low = bucket_boundaries[i]
                high = bucket_boundaries[i + 1]
                label = f"{low:.1f}-{high:.1f}"
                buckets[label] = {
                    "predicted_low": low,
                    "predicted_high": high,
                    "predicted_mid": round((low + high) / 2, 2),
                    "total": 0,
                    "positive": 0,
                    "actual_rate": 0.0,
                }

            try:
                with sqlite3.connect(da.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.execute(
                        """
                        SELECT rounds, consensus_reached, duration_seconds
                        FROM debate_records
                        WHERE created_at >= ? AND status = 'completed'
                        """,
                        (period_start.isoformat(),),
                    )
                    for row in cursor.fetchall():
                        rounds_val = row["rounds"] or 1
                        # Proxy predicted confidence from round efficiency
                        # Fewer rounds = higher expected confidence
                        predicted = max(0.0, min(1.0, 1.0 - (rounds_val - 1) / 15.0))
                        actual = 1 if row["consensus_reached"] else 0

                        # Place in appropriate bucket
                        for label, bucket in buckets.items():
                            if bucket["predicted_low"] <= predicted < bucket["predicted_high"]:
                                bucket["total"] += 1
                                bucket["positive"] += actual
                                break
                        else:
                            # Edge case: predicted == 1.0
                            last_label = list(buckets.keys())[-1]
                            buckets[last_label]["total"] += 1
                            buckets[last_label]["positive"] += actual

            except (sqlite3.Error, OSError) as e:
                logger.warning("Failed to build calibration data: %s", e)

            # Compute actual rates
            points = []
            for label, bucket in buckets.items():
                if bucket["total"] > 0:
                    bucket["actual_rate"] = round(bucket["positive"] / bucket["total"], 4)
                points.append(
                    {
                        "bucket": label,
                        "predicted": bucket["predicted_mid"],
                        "actual": bucket["actual_rate"],
                        "count": bucket["total"],
                    }
                )

            return {
                "points": points,
                "total_observations": sum(b["total"] for b in buckets.values()),
                "period": period,
            }
        except _SAFE_EXCEPTIONS as e:
            logger.warning("Failed to build calibration curve: %s", e)
            return {
                "points": [],
                "total_observations": 0,
                "period": period,
            }


__all__ = ["OutcomeDashboardHandler"]
