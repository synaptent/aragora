"""
Debate analytics endpoint methods for AnalyticsMetricsHandler.

Extracted from _analytics_metrics_impl.py for modularity.
Provides debate overview, trends, topics, and outcomes endpoints.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from aragora.config import CACHE_TTL_ANALYTICS

from ..base import (
    HandlerResult,
    handle_errors,
    json_response,
    ttl_cache,
)
from ._analytics_metrics_common import (
    VALID_GRANULARITIES,
    VALID_TIME_RANGES,
    _group_by_time,
    _parse_time_range,
)
from aragora.server.validation.query_params import safe_query_int


class DebateAnalyticsMixin:
    """Mixin providing debate analytics endpoint methods."""

    if TYPE_CHECKING:
        _validate_org_access: Any
        get_storage: Any

    # =========================================================================
    # Debate Analytics Endpoints
    # =========================================================================

    @ttl_cache(ttl_seconds=CACHE_TTL_ANALYTICS, key_prefix="analytics_debates_overview")
    @handle_errors("get debates overview")
    def _get_debates_overview(
        self, query_params: dict[str, Any], auth_context: Any | None = None
    ) -> HandlerResult:
        """
        Get debate overview statistics.

        GET /api/v1/analytics/debates/overview

        Query params:
        - time_range: Time range filter (7d, 30d, 90d, 365d, all) - default 30d
        - org_id: Filter by organization (optional, defaults to user's org)

        Response:
        {
            "time_range": "30d",
            "total_debates": 1250,
            "debates_this_period": 150,
            "debates_previous_period": 130,
            "growth_rate": 15.4,
            "consensus_reached": 1100,
            "consensus_rate": 88.0,
            "avg_rounds": 3.2,
            "avg_agents_per_debate": 3.5,
            "avg_confidence": 0.85,
            "generated_at": "2026-01-23T12:00:00Z"
        }
        """
        time_range = query_params.get("time_range", "30d")
        if time_range not in VALID_TIME_RANGES:
            time_range = "30d"

        # Validate org access
        requested_org_id = query_params.get("org_id")
        org_id, err = self._validate_org_access(auth_context, requested_org_id)
        if err:
            return err

        storage = self.get_storage()
        if not storage:
            return json_response(
                {
                    "time_range": time_range,
                    "total_debates": 0,
                    "debates_this_period": 0,
                    "consensus_reached": 0,
                    "consensus_rate": 0.0,
                    "avg_rounds": 0.0,
                    "avg_agents_per_debate": 0.0,
                    "avg_confidence": 0.0,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        # Get debates from storage
        debates = storage.list_debates(limit=10000, org_id=org_id)

        # Parse time range
        start_time = _parse_time_range(time_range)
        now = datetime.now(timezone.utc)

        # Filter debates by time range
        period_debates: list[dict[str, Any]] = []
        previous_period_debates: list[dict[str, Any]] = []
        all_debates: list[dict[str, Any]] = []

        for debate in debates:
            debate_dict = debate if isinstance(debate, dict) else vars(debate)
            created_at_str = debate_dict.get("created_at", "")

            if created_at_str:
                try:
                    if isinstance(created_at_str, datetime):
                        created_at = created_at_str
                    else:
                        created_at = datetime.fromisoformat(
                            str(created_at_str).replace("Z", "+00:00")
                        )
                except (ValueError, TypeError):
                    created_at = None
            else:
                created_at = None

            all_debates.append(debate_dict)

            if start_time and created_at:
                if created_at >= start_time:
                    period_debates.append(debate_dict)

                # Calculate previous period for comparison
                period_days = (now - start_time).days
                previous_start = start_time - timedelta(days=period_days)
                if previous_start <= created_at < start_time:
                    previous_period_debates.append(debate_dict)
            elif not start_time:
                period_debates.append(debate_dict)

        # Calculate metrics
        total_debates = len(all_debates)
        debates_this_period = len(period_debates)
        debates_previous_period = len(previous_period_debates)

        # Growth rate
        growth_rate = 0.0
        if debates_previous_period > 0:
            growth_rate = (
                (debates_this_period - debates_previous_period) / debates_previous_period
            ) * 100

        # Consensus metrics
        consensus_count = 0
        total_rounds = 0
        total_agents = 0
        total_confidence = 0.0
        confidence_count = 0

        for debate in period_debates:  # type: ignore[assignment]
            if debate.get("consensus_reached"):  # type: ignore[attr-defined]
                consensus_count += 1

            # Get rounds from result
            result = debate.get("result", {})  # type: ignore[attr-defined]
            if isinstance(result, dict):
                rounds: Any = result.get("rounds_used", result.get("rounds", 0))
                total_rounds += rounds
                confidence = result.get("confidence", 0.0)
                if confidence > 0:
                    total_confidence += confidence
                    confidence_count += 1

            # Count agents
            agents = debate.get("agents", [])  # type: ignore[attr-defined]
            if isinstance(agents, list):
                total_agents += len(agents)

        consensus_rate = (
            (consensus_count / debates_this_period * 100) if debates_this_period > 0 else 0.0
        )
        avg_rounds = total_rounds / debates_this_period if debates_this_period > 0 else 0.0
        avg_agents = total_agents / debates_this_period if debates_this_period > 0 else 0.0
        avg_confidence = total_confidence / confidence_count if confidence_count > 0 else 0.0

        return json_response(
            {
                "time_range": time_range,
                "total_debates": total_debates,
                "debates_this_period": debates_this_period,
                "debates_previous_period": debates_previous_period,
                "growth_rate": round(growth_rate, 1),
                "consensus_reached": consensus_count,
                "consensus_rate": round(consensus_rate, 1),
                "avg_rounds": round(avg_rounds, 1),
                "avg_agents_per_debate": round(avg_agents, 1),
                "avg_confidence": round(avg_confidence, 2),
                "generated_at": now.isoformat(),
            }
        )

    @ttl_cache(ttl_seconds=CACHE_TTL_ANALYTICS, key_prefix="analytics_debates_trends")
    @handle_errors("get debates trends")
    def _get_debates_trends(
        self, query_params: dict[str, Any], auth_context: Any | None = None
    ) -> HandlerResult:
        """
        Get debate trends over time.

        GET /api/v1/analytics/debates/trends

        Query params:
        - time_range: Time range filter (7d, 30d, 90d, 365d, all) - default 30d
        - granularity: Aggregation granularity (daily, weekly, monthly) - default daily
        - org_id: Filter by organization (optional, defaults to user's org)

        Response:
        {
            "time_range": "30d",
            "granularity": "daily",
            "data_points": [
                {
                    "period": "2026-01-01",
                    "total": 12,
                    "consensus_reached": 10,
                    "consensus_rate": 83.3,
                    "avg_rounds": 3.1
                },
                ...
            ],
            "generated_at": "2026-01-23T12:00:00Z"
        }
        """
        time_range = query_params.get("time_range", "30d")
        if time_range not in VALID_TIME_RANGES:
            time_range = "30d"

        granularity = query_params.get("granularity", "daily")
        if granularity not in VALID_GRANULARITIES:
            granularity = "daily"

        # Validate org access
        requested_org_id = query_params.get("org_id")
        org_id, err = self._validate_org_access(auth_context, requested_org_id)
        if err:
            return err

        storage = self.get_storage()
        if not storage:
            return json_response(
                {
                    "time_range": time_range,
                    "granularity": granularity,
                    "data_points": [],
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        # Get debates from storage
        debates = storage.list_debates(limit=10000, org_id=org_id)

        # Parse time range
        start_time = _parse_time_range(time_range)

        # Filter debates by time range and convert to dicts
        period_debates = []
        for debate in debates:
            debate_dict = debate if isinstance(debate, dict) else vars(debate)
            created_at_str = debate_dict.get("created_at", "")

            if created_at_str:
                try:
                    if isinstance(created_at_str, datetime):
                        created_at = created_at_str
                    else:
                        created_at = datetime.fromisoformat(
                            str(created_at_str).replace("Z", "+00:00")
                        )

                    if start_time is None or created_at >= start_time:
                        debate_dict["_parsed_time"] = created_at
                        period_debates.append(debate_dict)
                except (ValueError, TypeError):
                    continue

        # Group by time period
        groups = _group_by_time(period_debates, "_parsed_time", granularity)

        # Calculate metrics for each period
        data_points = []
        for period, debates_in_period in sorted(groups.items()):
            total = len(debates_in_period)
            consensus_count = sum(1 for d in debates_in_period if d.get("consensus_reached"))
            consensus_rate = (consensus_count / total * 100) if total > 0 else 0.0

            total_rounds = 0
            for d in debates_in_period:
                result = d.get("result", {})
                if isinstance(result, dict):
                    rounds: Any = result.get("rounds_used", result.get("rounds", 0))
                    total_rounds += rounds
            avg_rounds = total_rounds / total if total > 0 else 0.0

            data_points.append(
                {
                    "period": period,
                    "total": total,
                    "consensus_reached": consensus_count,
                    "consensus_rate": round(consensus_rate, 1),
                    "avg_rounds": round(avg_rounds, 1),
                }
            )

        return json_response(
            {
                "time_range": time_range,
                "granularity": granularity,
                "data_points": data_points,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    @ttl_cache(ttl_seconds=CACHE_TTL_ANALYTICS, key_prefix="analytics_debates_topics")
    @handle_errors("get debates topics")
    def _get_debates_topics(
        self, query_params: dict[str, Any], auth_context: Any | None = None
    ) -> HandlerResult:
        """
        Get topic distribution for debates.

        GET /api/v1/analytics/debates/topics

        Query params:
        - time_range: Time range filter (7d, 30d, 90d, 365d, all) - default 30d
        - limit: Maximum topics to return (default 20)
        - org_id: Filter by organization (optional, defaults to user's org)

        Response:
        {
            "time_range": "30d",
            "topics": [
                {
                    "topic": "security",
                    "count": 45,
                    "percentage": 18.5,
                    "consensus_rate": 92.0
                },
                ...
            ],
            "total_debates": 250,
            "generated_at": "2026-01-23T12:00:00Z"
        }
        """
        time_range = query_params.get("time_range", "30d")
        if time_range not in VALID_TIME_RANGES:
            time_range = "30d"

        limit = safe_query_int(query_params, "limit", default=20, max_val=100)

        # Validate org access
        requested_org_id = query_params.get("org_id")
        org_id, err = self._validate_org_access(auth_context, requested_org_id)
        if err:
            return err

        storage = self.get_storage()
        if not storage:
            return json_response(
                {
                    "time_range": time_range,
                    "topics": [],
                    "total_debates": 0,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        # Get debates from storage
        debates = storage.list_debates(limit=10000, org_id=org_id)

        # Parse time range
        start_time = _parse_time_range(time_range)

        # Extract topics and count
        topic_counts: Counter = Counter()
        topic_consensus: dict[str, list[bool]] = defaultdict(list)
        total_debates = 0

        for debate in debates:
            debate_dict = debate if isinstance(debate, dict) else vars(debate)
            created_at_str = debate_dict.get("created_at", "")

            # Check time range
            if start_time:
                try:
                    if isinstance(created_at_str, datetime):
                        created_at = created_at_str
                    else:
                        created_at = datetime.fromisoformat(
                            str(created_at_str).replace("Z", "+00:00")
                        )

                    if created_at < start_time:
                        continue
                except (ValueError, TypeError):
                    continue

            total_debates += 1

            # Extract topic from task or domain
            task = debate_dict.get("task", "")
            domain = debate_dict.get("domain", "")
            result = debate_dict.get("result", {})

            # Try to get domain from result metadata
            if isinstance(result, dict):
                domain = result.get("domain", domain)

            # Use domain if available, otherwise extract from task
            if domain:
                topic = domain.lower()
            elif task:
                # Simple topic extraction from task (first significant word)
                words = task.lower().split()
                topic = words[0] if words else "general"
            else:
                topic = "general"

            topic_counts[topic] += 1
            topic_consensus[topic].append(bool(debate_dict.get("consensus_reached")))

        # Build topic list with metrics
        topics = []
        for topic, count in topic_counts.most_common(limit):
            consensus_list = topic_consensus[topic]
            consensus_count = sum(1 for c in consensus_list if c)
            consensus_rate = (
                (consensus_count / len(consensus_list) * 100) if consensus_list else 0.0
            )
            percentage = (count / total_debates * 100) if total_debates > 0 else 0.0

            topics.append(
                {
                    "topic": topic,
                    "count": count,
                    "percentage": round(percentage, 1),
                    "consensus_rate": round(consensus_rate, 1),
                }
            )

        return json_response(
            {
                "time_range": time_range,
                "topics": topics,
                "total_debates": total_debates,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    @ttl_cache(ttl_seconds=CACHE_TTL_ANALYTICS, key_prefix="analytics_debates_outcomes")
    @handle_errors("get debates outcomes")
    def _get_debates_outcomes(
        self, query_params: dict[str, Any], auth_context: Any | None = None
    ) -> HandlerResult:
        """
        Get debate outcome distribution (win/loss/draw).

        GET /api/v1/analytics/debates/outcomes

        Query params:
        - time_range: Time range filter (7d, 30d, 90d, 365d, all) - default 30d
        - org_id: Filter by organization (optional, defaults to user's org)

        Response:
        {
            "time_range": "30d",
            "outcomes": {
                "consensus": 120,
                "majority": 45,
                "dissent": 15,
                "no_resolution": 10
            },
            "total_debates": 190,
            "by_confidence": {
                "high": {"count": 100, "consensus_rate": 95.0},
                "medium": {"count": 60, "consensus_rate": 80.0},
                "low": {"count": 30, "consensus_rate": 50.0}
            },
            "generated_at": "2026-01-23T12:00:00Z"
        }
        """
        time_range = query_params.get("time_range", "30d")
        if time_range not in VALID_TIME_RANGES:
            time_range = "30d"

        # Validate org access
        requested_org_id = query_params.get("org_id")
        org_id, err = self._validate_org_access(auth_context, requested_org_id)
        if err:
            return err

        storage = self.get_storage()
        if not storage:
            return json_response(
                {
                    "time_range": time_range,
                    "outcomes": {"consensus": 0, "majority": 0, "dissent": 0, "no_resolution": 0},
                    "total_debates": 0,
                    "by_confidence": {},
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        # Get debates from storage
        debates = storage.list_debates(limit=10000, org_id=org_id)

        # Parse time range
        start_time = _parse_time_range(time_range)

        # Count outcomes
        outcomes = {"consensus": 0, "majority": 0, "dissent": 0, "no_resolution": 0}
        confidence_buckets: dict[str, list[bool]] = {
            "high": [],
            "medium": [],
            "low": [],
        }
        total_debates = 0

        for debate in debates:
            debate_dict = debate if isinstance(debate, dict) else vars(debate)
            created_at_str = debate_dict.get("created_at", "")

            # Check time range
            if start_time:
                try:
                    if isinstance(created_at_str, datetime):
                        created_at = created_at_str
                    else:
                        created_at = datetime.fromisoformat(
                            str(created_at_str).replace("Z", "+00:00")
                        )

                    if created_at < start_time:
                        continue
                except (ValueError, TypeError):
                    continue

            total_debates += 1

            # Determine outcome
            consensus_reached = debate_dict.get("consensus_reached", False)
            result = debate_dict.get("result", {})
            confidence = 0.0

            if isinstance(result, dict):
                confidence = result.get("confidence", 0.0)
                outcome_type = result.get("outcome_type", "")

                if outcome_type == "consensus" or (consensus_reached and confidence >= 0.8):
                    outcomes["consensus"] += 1
                elif outcome_type == "majority" or (consensus_reached and confidence >= 0.5):
                    outcomes["majority"] += 1
                elif outcome_type == "dissent" or not consensus_reached:
                    if confidence >= 0.3:
                        outcomes["dissent"] += 1
                    else:
                        outcomes["no_resolution"] += 1
                else:
                    outcomes["no_resolution"] += 1
            else:
                if consensus_reached:
                    outcomes["consensus"] += 1
                else:
                    outcomes["no_resolution"] += 1

            # Bucket by confidence
            if confidence >= 0.8:
                confidence_buckets["high"].append(consensus_reached)
            elif confidence >= 0.5:
                confidence_buckets["medium"].append(consensus_reached)
            else:
                confidence_buckets["low"].append(consensus_reached)

        # Calculate confidence bucket metrics
        by_confidence = {}
        for bucket, consensus_list in confidence_buckets.items():
            count = len(consensus_list)
            if count > 0:
                consensus_count = sum(1 for c in consensus_list if c)
                consensus_rate = (consensus_count / count) * 100
                by_confidence[bucket] = {
                    "count": count,
                    "consensus_rate": round(consensus_rate, 1),
                }

        return json_response(
            {
                "time_range": time_range,
                "outcomes": outcomes,
                "total_debates": total_debates,
                "by_confidence": by_confidence,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
