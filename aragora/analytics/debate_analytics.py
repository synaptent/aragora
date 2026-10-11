"""
Debate Analytics Service.

Provides comprehensive analytics for multi-agent debates:
- Debate metrics: rounds, consensus rates, participation
- Agent performance: response times, accuracy, ELO trends
- Usage trends: daily/weekly/monthly patterns
- Cost analytics: per-debate, per-agent costs

This complements the main dashboard.py which focuses on audit findings.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class DebateTimeGranularity(str, Enum):
    """Time granularity for debate analytics."""

    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class DebateMetricType(str, Enum):
    """Types of debate metrics tracked."""

    DEBATE_COUNT = "debate_count"
    CONSENSUS_RATE = "consensus_rate"
    AVG_ROUNDS = "avg_rounds"
    AVG_DURATION = "avg_duration"
    AGENT_RESPONSE_TIME = "agent_response_time"
    AGENT_ACCURACY = "agent_accuracy"
    TOKEN_USAGE = "token_usage"  # noqa: S105 -- enum value
    COST_TOTAL = "cost_total"
    USER_ACTIVITY = "user_activity"
    ERROR_RATE = "error_rate"


@dataclass
class DebateStats:
    """Statistics for debates."""

    total_debates: int = 0
    completed_debates: int = 0
    failed_debates: int = 0
    consensus_reached: int = 0
    consensus_rate: float = 0.0
    avg_rounds: float = 0.0
    avg_duration_seconds: float = 0.0
    avg_agents_per_debate: float = 0.0
    total_messages: int = 0
    total_votes: int = 0
    period_start: datetime | None = None
    period_end: datetime | None = None
    by_protocol: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "total_debates": self.total_debates,
            "completed_debates": self.completed_debates,
            "failed_debates": self.failed_debates,
            "consensus_reached": self.consensus_reached,
            "consensus_rate": round(self.consensus_rate, 4),
            "avg_rounds": round(self.avg_rounds, 2),
            "avg_duration_seconds": round(self.avg_duration_seconds, 2),
            "avg_agents_per_debate": round(self.avg_agents_per_debate, 2),
            "total_messages": self.total_messages,
            "total_votes": self.total_votes,
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "by_protocol": self.by_protocol,
        }


@dataclass
class AgentPerformance:
    """Performance metrics for an agent."""

    agent_id: str = ""
    agent_name: str = ""
    provider: str = ""
    model: str = ""
    debates_participated: int = 0
    messages_sent: int = 0
    avg_response_time_ms: float = 0.0
    p95_response_time_ms: float = 0.0
    p99_response_time_ms: float = 0.0
    error_count: int = 0
    error_rate: float = 0.0
    votes_received: int = 0
    positive_votes: int = 0
    vote_ratio: float = 0.0
    consensus_contributions: int = 0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost: Decimal = Decimal("0")
    avg_cost_per_debate: Decimal = Decimal("0")
    current_elo: float = 1500.0
    elo_change_period: float = 0.0
    rank: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "provider": self.provider,
            "model": self.model,
            "debates_participated": self.debates_participated,
            "messages_sent": self.messages_sent,
            "avg_response_time_ms": round(self.avg_response_time_ms, 2),
            "p95_response_time_ms": round(self.p95_response_time_ms, 2),
            "p99_response_time_ms": round(self.p99_response_time_ms, 2),
            "error_count": self.error_count,
            "error_rate": round(self.error_rate, 4),
            "votes_received": self.votes_received,
            "positive_votes": self.positive_votes,
            "vote_ratio": round(self.vote_ratio, 4),
            "consensus_contributions": self.consensus_contributions,
            "total_tokens_in": self.total_tokens_in,
            "total_tokens_out": self.total_tokens_out,
            "total_cost": str(self.total_cost),
            "avg_cost_per_debate": str(self.avg_cost_per_debate),
            "current_elo": round(self.current_elo, 2),
            "elo_change_period": round(self.elo_change_period, 2),
            "rank": self.rank,
        }


@dataclass
class UsageTrendPoint:
    """Usage trend data point."""

    timestamp: datetime
    value: float
    metric: DebateMetricType

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "value": self.value,
            "metric": self.metric.value,
        }


@dataclass
class CostBreakdown:
    """Cost analytics and breakdown."""

    period_start: datetime
    period_end: datetime
    total_cost: Decimal = Decimal("0")
    by_provider: dict[str, Decimal] = field(default_factory=dict)
    by_model: dict[str, Decimal] = field(default_factory=dict)
    by_user: dict[str, Decimal] = field(default_factory=dict)
    by_org: dict[str, Decimal] = field(default_factory=dict)
    daily_costs: list[tuple[str, Decimal]] = field(default_factory=list)
    projected_monthly: Decimal = Decimal("0")
    cost_per_debate: Decimal = Decimal("0")
    cost_per_consensus: Decimal = Decimal("0")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "total_cost": str(self.total_cost),
            "by_provider": {k: str(v) for k, v in self.by_provider.items()},
            "by_model": {k: str(v) for k, v in self.by_model.items()},
            "by_user": {k: str(v) for k, v in self.by_user.items()},
            "by_org": {k: str(v) for k, v in self.by_org.items()},
            "daily_costs": [(d, str(c)) for d, c in self.daily_costs],
            "projected_monthly": str(self.projected_monthly),
            "cost_per_debate": str(self.cost_per_debate),
            "cost_per_consensus": str(self.cost_per_consensus),
        }


@dataclass
class DebateDashboardSummary:
    """Complete debate dashboard summary."""

    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    period_start: datetime | None = None
    period_end: datetime | None = None
    total_debates: int = 0
    total_users: int = 0
    total_organizations: int = 0
    active_agents: int = 0
    debate_stats: DebateStats | None = None
    cost_breakdown: CostBreakdown | None = None
    top_agents: list[AgentPerformance] = field(default_factory=list)
    debate_trend: list[UsageTrendPoint] = field(default_factory=list)
    cost_trend: list[UsageTrendPoint] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "generated_at": self.generated_at.isoformat(),
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "total_debates": self.total_debates,
            "total_users": self.total_users,
            "total_organizations": self.total_organizations,
            "active_agents": self.active_agents,
            "debate_stats": self.debate_stats.to_dict() if self.debate_stats else None,
            "cost_breakdown": self.cost_breakdown.to_dict() if self.cost_breakdown else None,
            "top_agents": [a.to_dict() for a in self.top_agents],
            "debate_trend": [t.to_dict() for t in self.debate_trend],
            "cost_trend": [t.to_dict() for t in self.cost_trend],
            "alerts": self.alerts,
        }


class DebateAnalytics:
    """
    Debate analytics service.

    Tracks and aggregates metrics for multi-agent debates.

    Example:
        analytics = DebateAnalytics()

        # Record a completed debate
        await analytics.record_debate(
            debate_id="debate123",
            rounds=9,
            consensus_reached=True,
            duration_seconds=120.5,
            agents=["claude", "gpt-4"],
        )

        # Get debate statistics
        stats = await analytics.get_debate_stats(days_back=30)

        # Get agent leaderboard
        agents = await analytics.get_agent_leaderboard(limit=10)

        # Get full dashboard summary
        summary = await analytics.get_dashboard_summary()
    """

    def __init__(self, db_path: str | None = None):
        """Initialize debate analytics."""
        if db_path is None:
            try:
                from aragora.persistence.db_config import get_default_data_dir

                data_dir = get_default_data_dir()
                data_dir.mkdir(parents=True, exist_ok=True)
                db_path = str(data_dir / "debate_analytics.db")
            except (ImportError, OSError):
                db_path = ":memory:"
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS debate_records (
                    id TEXT PRIMARY KEY,
                    debate_id TEXT NOT NULL,
                    org_id TEXT,
                    user_id TEXT,
                    status TEXT NOT NULL,
                    rounds INTEGER DEFAULT 0,
                    consensus_reached INTEGER DEFAULT 0,
                    duration_seconds REAL DEFAULT 0,
                    agents TEXT DEFAULT '[]',
                    protocol TEXT,
                    total_messages INTEGER DEFAULT 0,
                    total_votes INTEGER DEFAULT 0,
                    total_cost TEXT DEFAULT '0',
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_debate_records_org
                ON debate_records(org_id, created_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_debate_records_created
                ON debate_records(created_at)
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_records (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    agent_name TEXT,
                    provider TEXT,
                    model TEXT,
                    debate_id TEXT,
                    event_type TEXT NOT NULL,
                    response_time_ms REAL DEFAULT 0,
                    tokens_in INTEGER DEFAULT 0,
                    tokens_out INTEGER DEFAULT 0,
                    cost TEXT DEFAULT '0',
                    error INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_records_agent
                ON agent_records(agent_id, created_at)
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS elo_records (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    elo_rating REAL NOT NULL,
                    debate_id TEXT,
                    recorded_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_elo_records_agent
                ON elo_records(agent_id, recorded_at)
            """)

            conn.commit()

    async def record_debate(
        self,
        debate_id: str,
        rounds: int,
        consensus_reached: bool,
        duration_seconds: float,
        agents: list[str],
        status: str = "completed",
        org_id: str | None = None,
        user_id: str | None = None,
        protocol: str | None = None,
        total_messages: int = 0,
        total_votes: int = 0,
        total_cost: Decimal = Decimal("0"),
    ) -> None:
        """Record a debate event."""
        now = datetime.now(timezone.utc)
        event_id = f"debate_{uuid4().hex[:12]}"

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO debate_records (
                    id, debate_id, org_id, user_id, status, rounds,
                    consensus_reached, duration_seconds, agents, protocol,
                    total_messages, total_votes, total_cost, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    debate_id,
                    org_id,
                    user_id,
                    status,
                    rounds,
                    1 if consensus_reached else 0,
                    duration_seconds,
                    json.dumps(agents),
                    protocol,
                    total_messages,
                    total_votes,
                    str(total_cost),
                    now.isoformat(),
                    now.isoformat() if status == "completed" else None,
                ),
            )
            conn.commit()

    async def record_agent_activity(
        self,
        agent_id: str,
        debate_id: str,
        response_time_ms: float,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost: Decimal = Decimal("0"),
        error: bool = False,
        agent_name: str | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        """Record agent activity in a debate."""
        now = datetime.now(timezone.utc)
        event_id = f"agent_{uuid4().hex[:12]}"

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO agent_records (
                    id, agent_id, agent_name, provider, model, debate_id,
                    event_type, response_time_ms, tokens_in, tokens_out,
                    cost, error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    agent_id,
                    agent_name,
                    provider,
                    model,
                    debate_id,
                    "message",
                    response_time_ms,
                    tokens_in,
                    tokens_out,
                    str(cost),
                    1 if error else 0,
                    now.isoformat(),
                ),
            )
            conn.commit()

    async def record_elo_update(
        self,
        agent_id: str,
        elo_rating: float,
        debate_id: str | None = None,
    ) -> None:
        """Record agent ELO rating update."""
        now = datetime.now(timezone.utc)
        event_id = f"elo_{uuid4().hex[:12]}"

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO elo_records (
                    id, agent_id, elo_rating, debate_id, recorded_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (event_id, agent_id, elo_rating, debate_id, now.isoformat()),
            )
            conn.commit()

    async def get_debate_stats(
        self,
        org_id: str | None = None,
        days_back: int = 30,
    ) -> DebateStats:
        """Get debate statistics for a period."""
        period_end = datetime.now(timezone.utc)
        period_start = period_end - timedelta(days=days_back)

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row

            if org_id:
                cursor = conn.execute(
                    """
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                        SUM(consensus_reached) as consensus,
                        AVG(rounds) as avg_rounds,
                        AVG(duration_seconds) as avg_duration,
                        SUM(total_messages) as messages,
                        SUM(total_votes) as votes
                    FROM debate_records
                    WHERE org_id = ? AND created_at >= ?
                    """,
                    (org_id, period_start.isoformat()),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                        SUM(consensus_reached) as consensus,
                        AVG(rounds) as avg_rounds,
                        AVG(duration_seconds) as avg_duration,
                        SUM(total_messages) as messages,
                        SUM(total_votes) as votes
                    FROM debate_records
                    WHERE created_at >= ?
                    """,
                    (period_start.isoformat(),),
                )

            row = cursor.fetchone()
            total = row["total"] or 0
            completed = row["completed"] or 0
            consensus = row["consensus"] or 0

            return DebateStats(
                total_debates=total,
                completed_debates=completed,
                failed_debates=row["failed"] or 0,
                consensus_reached=consensus,
                consensus_rate=consensus / completed if completed > 0 else 0.0,
                avg_rounds=row["avg_rounds"] or 0.0,
                avg_duration_seconds=row["avg_duration"] or 0.0,
                total_messages=row["messages"] or 0,
                total_votes=row["votes"] or 0,
                period_start=period_start,
                period_end=period_end,
            )

    async def get_agent_performance(
        self,
        agent_id: str,
        days_back: int = 30,
    ) -> AgentPerformance:
        """Get performance metrics for an agent."""
        period_start = datetime.now(timezone.utc) - timedelta(days=days_back)

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row

            cursor = conn.execute(
                """
                SELECT
                    agent_name,
                    provider,
                    model,
                    COUNT(*) as messages,
                    COUNT(DISTINCT debate_id) as debates,
                    AVG(response_time_ms) as avg_rt,
                    SUM(tokens_in) as tokens_in,
                    SUM(tokens_out) as tokens_out,
                    SUM(CAST(cost AS REAL)) as total_cost,
                    SUM(error) as errors
                FROM agent_records
                WHERE agent_id = ? AND created_at >= ?
                GROUP BY agent_id
                """,
                (agent_id, period_start.isoformat()),
            )

            row = cursor.fetchone()
            if not row:
                return AgentPerformance(agent_id=agent_id)

            messages = row["messages"] or 0
            errors = row["errors"] or 0
            debates = row["debates"] or 0

            # Get current ELO
            cursor = conn.execute(
                """
                SELECT elo_rating FROM elo_records
                WHERE agent_id = ?
                ORDER BY recorded_at DESC LIMIT 1
                """,
                (agent_id,),
            )
            elo_row = cursor.fetchone()
            current_elo = elo_row[0] if elo_row else 1500.0

            return AgentPerformance(
                agent_id=agent_id,
                agent_name=row["agent_name"] or agent_id,
                provider=row["provider"] or "",
                model=row["model"] or "",
                debates_participated=debates,
                messages_sent=messages,
                avg_response_time_ms=row["avg_rt"] or 0.0,
                error_count=errors,
                error_rate=errors / messages if messages > 0 else 0.0,
                total_tokens_in=row["tokens_in"] or 0,
                total_tokens_out=row["tokens_out"] or 0,
                total_cost=Decimal(str(row["total_cost"] or 0)),
                avg_cost_per_debate=(
                    Decimal(str((row["total_cost"] or 0) / debates))
                    if debates > 0
                    else Decimal("0")
                ),
                current_elo=current_elo,
            )

    async def get_agent_leaderboard(
        self,
        limit: int = 10,
        days_back: int = 30,
        sort_by: str = "elo",
    ) -> list[AgentPerformance]:
        """Get agent leaderboard."""
        period_start = datetime.now(timezone.utc) - timedelta(days=days_back)

        with closing(sqlite3.connect(self.db_path)) as conn:
            cursor = conn.execute(
                """
                SELECT DISTINCT agent_id
                FROM agent_records
                WHERE created_at >= ?
                """,
                (period_start.isoformat(),),
            )
            agent_ids = [row[0] for row in cursor.fetchall()]

        agents = []
        for agent_id in agent_ids:
            metrics = await self.get_agent_performance(agent_id, days_back)
            agents.append(metrics)

        if sort_by == "elo":
            agents.sort(key=lambda a: a.current_elo, reverse=True)
        elif sort_by == "debates":
            agents.sort(key=lambda a: a.debates_participated, reverse=True)
        elif sort_by == "messages":
            agents.sort(key=lambda a: a.messages_sent, reverse=True)

        for i, agent in enumerate(agents[:limit]):
            agent.rank = i + 1

        return agents[:limit]

    async def get_usage_trends(
        self,
        metric: DebateMetricType,
        granularity: DebateTimeGranularity = DebateTimeGranularity.DAILY,
        days_back: int = 30,
        org_id: str | None = None,
    ) -> list[UsageTrendPoint]:
        """Get usage trends over time."""
        period_start = datetime.now(timezone.utc) - timedelta(days=days_back)

        if granularity == DebateTimeGranularity.HOURLY:
            group_by = "strftime('%Y-%m-%d %H:00:00', created_at)"
        elif granularity == DebateTimeGranularity.WEEKLY:
            group_by = "strftime('%Y-W%W', created_at)"
        elif granularity == DebateTimeGranularity.MONTHLY:
            group_by = "strftime('%Y-%m', created_at)"
        else:
            group_by = "date(created_at)"

        trends = []

        with closing(sqlite3.connect(self.db_path)) as conn:
            if metric == DebateMetricType.DEBATE_COUNT:
                if org_id:
                    query = f"""
                        SELECT {group_by} as period, COUNT(*) as value
                        FROM debate_records
                        WHERE org_id = ? AND created_at >= ?
                        GROUP BY period ORDER BY period
                    """  # dynamic clause from internal state
                    cursor = conn.execute(query, (org_id, period_start.isoformat()))
                else:
                    query = f"""
                        SELECT {group_by} as period, COUNT(*) as value
                        FROM debate_records
                        WHERE created_at >= ?
                        GROUP BY period ORDER BY period
                    """  # dynamic clause from internal state
                    cursor = conn.execute(query, (period_start.isoformat(),))

                for row in cursor.fetchall():
                    if row[0]:
                        try:
                            ts = datetime.strptime(row[0], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                            trends.append(
                                UsageTrendPoint(
                                    timestamp=ts,
                                    value=float(row[1] or 0),
                                    metric=metric,
                                )
                            )
                        except ValueError:
                            continue

        return trends

    async def get_cost_breakdown(
        self,
        days_back: int = 30,
        org_id: str | None = None,
    ) -> CostBreakdown:
        """Get cost analytics breakdown."""
        period_end = datetime.now(timezone.utc)
        period_start = period_end - timedelta(days=days_back)

        with closing(sqlite3.connect(self.db_path)) as conn:
            # Total cost
            if org_id:
                cursor = conn.execute(
                    """
                    SELECT SUM(CAST(total_cost AS REAL)) as total
                    FROM debate_records
                    WHERE org_id = ? AND created_at >= ?
                    """,
                    (org_id, period_start.isoformat()),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT SUM(CAST(total_cost AS REAL)) as total
                    FROM debate_records
                    WHERE created_at >= ?
                    """,
                    (period_start.isoformat(),),
                )

            row = cursor.fetchone()
            total_cost = Decimal(str(row[0] or 0))

            # By provider
            cursor = conn.execute(
                """
                SELECT provider, SUM(CAST(cost AS REAL)) as total
                FROM agent_records
                WHERE created_at >= ?
                GROUP BY provider
                """,
                (period_start.isoformat(),),
            )
            by_provider = {row[0]: Decimal(str(row[1])) for row in cursor.fetchall() if row[0]}

            # By model
            cursor = conn.execute(
                """
                SELECT model, SUM(CAST(cost AS REAL)) as total
                FROM agent_records
                WHERE created_at >= ?
                GROUP BY model
                """,
                (period_start.isoformat(),),
            )
            by_model = {row[0]: Decimal(str(row[1])) for row in cursor.fetchall() if row[0]}

            return CostBreakdown(
                period_start=period_start,
                period_end=period_end,
                total_cost=total_cost,
                by_provider=by_provider,
                by_model=by_model,
            )

    async def get_dashboard_summary(
        self,
        org_id: str | None = None,
        days_back: int = 30,
    ) -> DebateDashboardSummary:
        """Get complete debate dashboard summary."""
        period_end = datetime.now(timezone.utc)
        period_start = period_end - timedelta(days=days_back)

        debate_stats = await self.get_debate_stats(org_id=org_id, days_back=days_back)
        cost_breakdown = await self.get_cost_breakdown(days_back=days_back, org_id=org_id)
        top_agents = await self.get_agent_leaderboard(limit=5, days_back=days_back)
        debate_trend = await self.get_usage_trends(
            DebateMetricType.DEBATE_COUNT,
            DebateTimeGranularity.DAILY,
            days_back,
            org_id,
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            cursor = conn.execute(
                """
                SELECT COUNT(DISTINCT agent_id)
                FROM agent_records
                WHERE created_at >= ?
                """,
                (period_start.isoformat(),),
            )
            active_agents = cursor.fetchone()[0] or 0

        alerts = []
        if debate_stats.consensus_rate < 0.5:
            alerts.append(
                {
                    "level": "warning",
                    "message": f"Low consensus rate: {debate_stats.consensus_rate:.1%}",
                    "metric": "consensus_rate",
                }
            )

        return DebateDashboardSummary(
            period_start=period_start,
            period_end=period_end,
            total_debates=debate_stats.total_debates,
            active_agents=active_agents,
            debate_stats=debate_stats,
            cost_breakdown=cost_breakdown,
            top_agents=top_agents,
            debate_trend=debate_trend,
            alerts=alerts,
        )


# Global instance
_debate_analytics: DebateAnalytics | None = None
_lock = threading.Lock()


def get_debate_analytics(db_path: str | None = None) -> DebateAnalytics:
    """Get or create global debate analytics instance."""
    global _debate_analytics
    if _debate_analytics is None:
        with _lock:
            if _debate_analytics is None:
                _debate_analytics = DebateAnalytics(db_path=db_path)
    return _debate_analytics


__all__ = [
    "DebateAnalytics",
    "DebateTimeGranularity",
    "DebateMetricType",
    "DebateStats",
    "AgentPerformance",
    "UsageTrendPoint",
    "CostBreakdown",
    "DebateDashboardSummary",
    "get_debate_analytics",
]
