"""
Debate Store - Persistent storage and statistics for deliberations.

Provides analytics and statistics methods for deliberation tracking:
- Deliberation summary statistics
- Channel-level breakdowns
- Consensus rates by team composition
- Performance metrics (latency, cost, efficiency)
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from collections.abc import Iterator

from aragora.config import DB_TIMEOUT_SECONDS
from aragora.persistence.db_config import DatabaseType, get_db_path

logger = logging.getLogger(__name__)

# Singleton instance
_debate_store: DebateStore | None = None


def get_debate_store() -> DebateStore:
    """Get or create the singleton DebateStore instance."""
    global _debate_store
    if _debate_store is None:
        _debate_store = DebateStore()
    return _debate_store


class DebateStore:
    """
    Persistent storage and analytics for deliberations.

    Tracks deliberation metadata, outcomes, and performance metrics
    to support the analytics dashboard endpoints.
    """

    def __init__(self, db_path: Path | None = None):
        """Initialize the debate store with the given database path."""
        self.db_path = db_path or get_db_path(DatabaseType.DEBATES)
        self._ensure_schema()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Get a database connection with row factory."""
        conn = sqlite3.connect(str(self.db_path), timeout=DB_TIMEOUT_SECONDS)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        """Ensure the deliberation tables exist."""
        with self._connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS deliberations (
                    id TEXT PRIMARY KEY,
                    org_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    consensus_reached INTEGER DEFAULT 0,
                    template TEXT,
                    priority TEXT DEFAULT 'normal',
                    platform TEXT,
                    channel_id TEXT,
                    channel_name TEXT,
                    team_agents TEXT,
                    rounds INTEGER DEFAULT 0,
                    duration_seconds REAL DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    total_cost_usd REAL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    metadata TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_deliberations_org_id
                    ON deliberations(org_id);
                CREATE INDEX IF NOT EXISTS idx_deliberations_created_at
                    ON deliberations(created_at);
                CREATE INDEX IF NOT EXISTS idx_deliberations_status
                    ON deliberations(status);
                CREATE INDEX IF NOT EXISTS idx_deliberations_platform
                    ON deliberations(platform);

                CREATE TABLE IF NOT EXISTS deliberation_agents (
                    deliberation_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    agent_name TEXT,
                    tokens_used INTEGER DEFAULT 0,
                    cost_usd REAL DEFAULT 0,
                    agreed_with_consensus INTEGER DEFAULT 0,
                    PRIMARY KEY (deliberation_id, agent_id),
                    FOREIGN KEY (deliberation_id) REFERENCES deliberations(id)
                );

                CREATE INDEX IF NOT EXISTS idx_delib_agents_agent_id
                    ON deliberation_agents(agent_id);
                """)
            conn.commit()

    def get_deliberation_stats(
        self,
        org_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> dict[str, Any]:
        """
        Get deliberation statistics for the given organization and time range.

        Returns:
            Dictionary with:
            - total: Total deliberations
            - completed: Completed deliberations
            - in_progress: In-progress deliberations
            - failed: Failed deliberations
            - consensus_reached: Number that reached consensus
            - avg_rounds: Average number of rounds
            - avg_duration_seconds: Average duration
            - by_template: Breakdown by template
            - by_priority: Breakdown by priority
        """
        with self._connection() as conn:
            # Get status counts
            status_rows = conn.execute(
                """
                SELECT status, COUNT(*) as count
                FROM deliberations
                WHERE org_id = ?
                    AND created_at >= ?
                    AND created_at <= ?
                GROUP BY status
                """,
                (org_id, start_time.isoformat(), end_time.isoformat()),
            ).fetchall()

            status_counts = {row["status"]: row["count"] for row in status_rows}

            # Get overall stats
            stats_row = conn.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(consensus_reached) as consensus_count,
                    AVG(rounds) as avg_rounds,
                    AVG(duration_seconds) as avg_duration
                FROM deliberations
                WHERE org_id = ?
                    AND created_at >= ?
                    AND created_at <= ?
                """,
                (org_id, start_time.isoformat(), end_time.isoformat()),
            ).fetchone()

            # Get template breakdown
            template_rows = conn.execute(
                """
                SELECT template, COUNT(*) as count
                FROM deliberations
                WHERE org_id = ?
                    AND created_at >= ?
                    AND created_at <= ?
                    AND template IS NOT NULL
                GROUP BY template
                """,
                (org_id, start_time.isoformat(), end_time.isoformat()),
            ).fetchall()

            # Get priority breakdown
            priority_rows = conn.execute(
                """
                SELECT priority, COUNT(*) as count
                FROM deliberations
                WHERE org_id = ?
                    AND created_at >= ?
                    AND created_at <= ?
                GROUP BY priority
                """,
                (org_id, start_time.isoformat(), end_time.isoformat()),
            ).fetchall()

            return {
                "total": stats_row["total"] or 0,
                "completed": status_counts.get("completed", 0),
                "in_progress": status_counts.get("in_progress", 0),
                "failed": status_counts.get("failed", 0),
                "consensus_reached": stats_row["consensus_count"] or 0,
                "avg_rounds": stats_row["avg_rounds"] or 0,
                "avg_duration_seconds": stats_row["avg_duration"] or 0,
                "by_template": {row["template"]: row["count"] for row in template_rows},
                "by_priority": {row["priority"]: row["count"] for row in priority_rows},
            }

    def get_deliberation_stats_by_channel(
        self,
        org_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict[str, Any]]:
        """
        Get deliberation statistics broken down by channel.

        Returns:
            List of channel statistics dictionaries.
        """
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    platform,
                    channel_id,
                    channel_name,
                    COUNT(*) as total_deliberations,
                    SUM(consensus_reached) as consensus_reached,
                    SUM(duration_seconds) as total_duration,
                    AVG(duration_seconds) as avg_duration_seconds,
                    GROUP_CONCAT(DISTINCT template) as templates
                FROM deliberations
                WHERE org_id = ?
                    AND created_at >= ?
                    AND created_at <= ?
                GROUP BY platform, channel_id, channel_name
                ORDER BY total_deliberations DESC
                """,
                (org_id, start_time.isoformat(), end_time.isoformat()),
            ).fetchall()

            results = []
            for row in rows:
                total = row["total_deliberations"]
                consensus = row["consensus_reached"] or 0
                consensus_rate = f"{(consensus / total * 100):.0f}%" if total > 0 else "0%"

                templates = row["templates"].split(",") if row["templates"] else []

                results.append(
                    {
                        "platform": row["platform"] or "api",
                        "channel_id": row["channel_id"],
                        "channel_name": row["channel_name"],
                        "total_deliberations": total,
                        "consensus_reached": consensus,
                        "consensus_rate": consensus_rate,
                        "total_duration": row["total_duration"] or 0,
                        "avg_duration_seconds": row["avg_duration_seconds"] or 0,
                        "top_templates": templates[:3],
                    }
                )

            return results

    def get_consensus_stats(
        self,
        org_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> dict[str, Any]:
        """
        Get consensus statistics by team composition.

        Returns:
            Dictionary with:
            - overall_consensus_rate: Overall rate
            - by_team_size: Breakdown by team size
            - by_agent: Per-agent statistics
            - top_teams: Best performing team compositions
        """
        with self._connection() as conn:
            # Overall consensus rate
            overall_row = conn.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(consensus_reached) as consensus_count
                FROM deliberations
                WHERE org_id = ?
                    AND created_at >= ?
                    AND created_at <= ?
                    AND status = 'completed'
                """,
                (org_id, start_time.isoformat(), end_time.isoformat()),
            ).fetchone()

            total = overall_row["total"] or 0
            consensus_count = overall_row["consensus_count"] or 0
            overall_rate = f"{(consensus_count / total * 100):.0f}%" if total > 0 else "0%"

            # Per-agent stats
            agent_rows = conn.execute(
                """
                SELECT
                    da.agent_id,
                    da.agent_name,
                    COUNT(*) as participations,
                    SUM(da.agreed_with_consensus) as consensus_contributions,
                    AVG(da.agreed_with_consensus) as avg_agreement
                FROM deliberation_agents da
                JOIN deliberations d ON d.id = da.deliberation_id
                WHERE d.org_id = ?
                    AND d.created_at >= ?
                    AND d.created_at <= ?
                GROUP BY da.agent_id, da.agent_name
                ORDER BY participations DESC
                """,
                (org_id, start_time.isoformat(), end_time.isoformat()),
            ).fetchall()

            by_agent = []
            for row in agent_rows:
                participations = row["participations"]
                contributions = row["consensus_contributions"] or 0
                rate = (
                    f"{(contributions / participations * 100):.0f}%" if participations > 0 else "0%"
                )

                by_agent.append(
                    {
                        "agent_id": row["agent_id"],
                        "agent_name": row["agent_name"] or row["agent_id"],
                        "participations": participations,
                        "consensus_contributions": contributions,
                        "consensus_rate": rate,
                        "avg_agreement_score": round(row["avg_agreement"] or 0, 2),
                    }
                )

            # Team size breakdown (estimated from team_agents JSON length)
            size_rows = conn.execute(
                """
                SELECT
                    LENGTH(team_agents) - LENGTH(REPLACE(team_agents, ',', '')) + 1 as team_size,
                    COUNT(*) as count,
                    SUM(consensus_reached) as consensus_count
                FROM deliberations
                WHERE org_id = ?
                    AND created_at >= ?
                    AND created_at <= ?
                    AND team_agents IS NOT NULL
                    AND status = 'completed'
                GROUP BY team_size
                """,
                (org_id, start_time.isoformat(), end_time.isoformat()),
            ).fetchall()

            by_team_size = {}
            for row in size_rows:
                size = str(row["team_size"])
                count = row["count"]
                consensus = row["consensus_count"] or 0
                rate = f"{(consensus / count * 100):.0f}%" if count > 0 else "0%"
                by_team_size[size] = {"count": count, "consensus_rate": rate}

            # Top teams (by consensus rate, min 3 deliberations)
            team_rows = conn.execute(
                """
                SELECT
                    team_agents,
                    COUNT(*) as deliberations,
                    SUM(consensus_reached) as consensus_count
                FROM deliberations
                WHERE org_id = ?
                    AND created_at >= ?
                    AND created_at <= ?
                    AND team_agents IS NOT NULL
                    AND status = 'completed'
                GROUP BY team_agents
                HAVING COUNT(*) >= 3
                ORDER BY (CAST(SUM(consensus_reached) AS REAL) / COUNT(*)) DESC
                LIMIT 10
                """,
                (org_id, start_time.isoformat(), end_time.isoformat()),
            ).fetchall()

            top_teams = []
            for row in team_rows:
                delibs = row["deliberations"]
                consensus = row["consensus_count"] or 0
                rate = f"{(consensus / delibs * 100):.0f}%" if delibs > 0 else "0%"

                # Parse team agents list
                team_str = row["team_agents"] or ""
                team = [a.strip() for a in team_str.split(",") if a.strip()]

                top_teams.append(
                    {
                        "team": team,
                        "deliberations": delibs,
                        "consensus_rate": rate,
                    }
                )

            return {
                "overall_consensus_rate": overall_rate,
                "by_team_size": by_team_size,
                "by_agent": by_agent,
                "top_teams": top_teams,
            }

    def get_deliberation_performance(
        self,
        org_id: str,
        start_time: datetime,
        end_time: datetime,
        granularity: str = "day",
    ) -> dict[str, Any]:
        """
        Get deliberation performance metrics.

        Returns:
            Dictionary with:
            - summary: Overall performance summary
            - by_template: Performance by template
            - trends: Time-series performance data
            - cost_by_agent: Cost breakdown by agent
        """
        with self._connection() as conn:
            # Summary stats
            summary_row = conn.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(total_cost_usd) as total_cost,
                    SUM(total_tokens) as total_tokens,
                    AVG(duration_seconds) as avg_duration,
                    AVG(rounds) as avg_rounds
                FROM deliberations
                WHERE org_id = ?
                    AND created_at >= ?
                    AND created_at <= ?
                """,
                (org_id, start_time.isoformat(), end_time.isoformat()),
            ).fetchone()

            total = summary_row["total"] or 0
            total_cost = summary_row["total_cost"] or 0
            total_tokens = summary_row["total_tokens"] or 0

            # Get percentiles for duration
            duration_rows = conn.execute(
                """
                SELECT duration_seconds
                FROM deliberations
                WHERE org_id = ?
                    AND created_at >= ?
                    AND created_at <= ?
                    AND duration_seconds > 0
                ORDER BY duration_seconds
                """,
                (org_id, start_time.isoformat(), end_time.isoformat()),
            ).fetchall()

            durations = [row["duration_seconds"] for row in duration_rows]
            p50 = durations[len(durations) // 2] if durations else 0
            p95_idx = int(len(durations) * 0.95) if durations else 0
            p95 = durations[p95_idx] if durations and p95_idx < len(durations) else 0

            summary = {
                "total_deliberations": total,
                "total_cost_usd": f"{total_cost:.2f}",
                "avg_cost_per_deliberation": f"{(total_cost / total):.2f}" if total > 0 else "0.00",
                "total_tokens": total_tokens,
                "avg_tokens_per_deliberation": int(total_tokens / total) if total > 0 else 0,
                "avg_duration_seconds": round(summary_row["avg_duration"] or 0, 1),
                "p50_duration_seconds": round(p50, 1),
                "p95_duration_seconds": round(p95, 1),
                "avg_rounds": round(summary_row["avg_rounds"] or 0, 1),
            }

            # By template
            template_rows = conn.execute(
                """
                SELECT
                    template,
                    COUNT(*) as count,
                    AVG(total_cost_usd) as avg_cost,
                    AVG(duration_seconds) as avg_duration,
                    AVG(rounds) as avg_rounds
                FROM deliberations
                WHERE org_id = ?
                    AND created_at >= ?
                    AND created_at <= ?
                    AND template IS NOT NULL
                GROUP BY template
                ORDER BY count DESC
                """,
                (org_id, start_time.isoformat(), end_time.isoformat()),
            ).fetchall()

            by_template = [
                {
                    "template": row["template"],
                    "count": row["count"],
                    "avg_cost": f"{(row['avg_cost'] or 0):.2f}",
                    "avg_duration_seconds": round(row["avg_duration"] or 0, 1),
                    "avg_rounds": round(row["avg_rounds"] or 0, 1),
                }
                for row in template_rows
            ]

            # Trends
            if granularity == "day":
                date_format = "DATE(created_at)"
            else:
                date_format = "strftime('%Y-W%W', created_at)"

            trend_rows = conn.execute(
                f"""
                SELECT
                    {date_format} as period,
                    COUNT(*) as count,
                    AVG(duration_seconds) as avg_duration,
                    SUM(total_cost_usd) as total_cost
                FROM deliberations
                WHERE org_id = ?
                    AND created_at >= ?
                    AND created_at <= ?
                GROUP BY {date_format}
                ORDER BY period
                """,  # internal query construction
                (org_id, start_time.isoformat(), end_time.isoformat()),
            ).fetchall()

            trends = [
                {
                    "date": row["period"],
                    "count": row["count"],
                    "avg_duration_seconds": round(row["avg_duration"] or 0, 1),
                    "total_cost": f"{(row['total_cost'] or 0):.2f}",
                }
                for row in trend_rows
            ]

            # Cost by agent
            agent_cost_rows = conn.execute(
                """
                SELECT
                    da.agent_id,
                    SUM(da.cost_usd) as total_cost
                FROM deliberation_agents da
                JOIN deliberations d ON d.id = da.deliberation_id
                WHERE d.org_id = ?
                    AND d.created_at >= ?
                    AND d.created_at <= ?
                GROUP BY da.agent_id
                ORDER BY total_cost DESC
                """,
                (org_id, start_time.isoformat(), end_time.isoformat()),
            ).fetchall()

            cost_by_agent = {
                row["agent_id"]: f"{(row['total_cost'] or 0):.2f}" for row in agent_cost_rows
            }

            return {
                "summary": summary,
                "by_template": by_template,
                "trends": trends,
                "cost_by_agent": cost_by_agent,
            }

    def get_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent deliberations.

        Args:
            limit: Maximum number of deliberations to return.

        Returns:
            List of deliberation dictionaries.
        """
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT id, org_id, question, status, consensus_reached,
                       template, priority, platform, channel_id, channel_name,
                       team_agents, rounds, duration_seconds, total_tokens,
                       total_cost_usd, created_at, completed_at, metadata
                FROM deliberations
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

            return [dict(row) for row in rows]

    def get(self, deliberation_id: str) -> dict[str, Any] | None:
        """Get a single deliberation by ID.

        Args:
            deliberation_id: The deliberation ID.

        Returns:
            Deliberation dictionary or None if not found.
        """
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT id, org_id, question, status, consensus_reached,
                       template, priority, platform, channel_id, channel_name,
                       team_agents, rounds, duration_seconds, total_tokens,
                       total_cost_usd, created_at, completed_at, metadata
                FROM deliberations
                WHERE id = ?
                """,
                (deliberation_id,),
            ).fetchone()

            return dict(row) if row else None

    def record_deliberation(
        self,
        deliberation_id: str,
        org_id: str,
        question: str,
        status: str = "pending",
        template: str | None = None,
        priority: str = "normal",
        platform: str | None = None,
        channel_id: str | None = None,
        channel_name: str | None = None,
        team_agents: list[str] | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Record a new deliberation."""
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO deliberations (
                    id, org_id, question, status, template, priority,
                    platform, channel_id, channel_name, team_agents,
                    created_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    deliberation_id,
                    org_id,
                    question,
                    status,
                    template,
                    priority,
                    platform,
                    channel_id,
                    channel_name,
                    ",".join(team_agents) if team_agents else None,
                    datetime.now(timezone.utc).isoformat(),
                    str(metadata) if metadata else None,
                ),
            )
            conn.commit()

    def update_deliberation_result(
        self,
        deliberation_id: str,
        status: str,
        consensus_reached: bool,
        rounds: int,
        duration_seconds: float,
        total_tokens: int = 0,
        total_cost_usd: float = 0,
    ) -> None:
        """Update a deliberation with its result."""
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE deliberations
                SET status = ?,
                    consensus_reached = ?,
                    rounds = ?,
                    duration_seconds = ?,
                    total_tokens = ?,
                    total_cost_usd = ?,
                    completed_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    1 if consensus_reached else 0,
                    rounds,
                    duration_seconds,
                    total_tokens,
                    total_cost_usd,
                    datetime.now(timezone.utc).isoformat(),
                    deliberation_id,
                ),
            )
            conn.commit()

    def record_agent_participation(
        self,
        deliberation_id: str,
        agent_id: str,
        agent_name: str | None = None,
        tokens_used: int = 0,
        cost_usd: float = 0,
        agreed_with_consensus: bool = False,
    ) -> None:
        """Record an agent's participation in a deliberation."""
        with self._connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO deliberation_agents (
                    deliberation_id, agent_id, agent_name,
                    tokens_used, cost_usd, agreed_with_consensus
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    deliberation_id,
                    agent_id,
                    agent_name,
                    tokens_used,
                    cost_usd,
                    1 if agreed_with_consensus else 0,
                ),
            )
            conn.commit()
