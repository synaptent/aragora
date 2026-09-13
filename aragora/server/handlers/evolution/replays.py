"""
Replays and learning evolution endpoint handlers.

Endpoints:
- GET /api/replays - List available replays
- GET /api/replays/:replay_id - Get specific replay with events
- GET /api/learning/evolution - Get meta-learning patterns
- GET /api/meta-learning/stats - Get meta-learning hyperparameters and efficiency stats
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aragora.config import DEFAULT_ROUNDS

if TYPE_CHECKING:
    pass

from aragora.config import (
    CACHE_TTL_LEARNING_EVOLUTION,
    CACHE_TTL_META_LEARNING,
    CACHE_TTL_REPLAYS_LIST,
)
from aragora.memory.database import MemoryDatabase
from aragora.server.versioning.compat import strip_version_prefix

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    get_int_param,
    handle_errors,
    json_response,
    safe_json_parse,
    ttl_cache,
)
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter for replays endpoints (30 requests per minute - file operations)
_replays_limiter = RateLimiter(requests_per_minute=30)


class ReplaysHandler(BaseHandler):
    """Handler for replays and learning evolution endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/replays",
        "/api/learning/evolution",
        "/api/meta-learning/stats",
        "/api/v1/replays",
        "/api/v1/replays/compare",
        "/api/v1/replays/search",
        "/api/v1/replays/stats",
        "/api/v1/learning/evolution",
        "/api/v1/meta-learning/stats",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        normalized = strip_version_prefix(path)
        if normalized in ("/api/replays", "/api/learning/evolution", "/api/meta-learning/stats"):
            return True
        # Dynamic route for specific replay: /api/replays/{id}
        # Normalized split gives ['', 'api', 'replays', '{id}'] = 4 parts
        if normalized.startswith("/api/replays/") and len(normalized.split("/")) == 4:
            return True
        return False

    def _apply_rate_limit(self, handler: Any) -> HandlerResult | None:
        """Apply rate limiting. Returns error response if limit exceeded, None otherwise."""
        client_ip = get_client_ip(handler)
        if not _replays_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for replays endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)
        return None

    def handle(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route replay requests to appropriate methods."""
        nomic_dir = self.ctx.get("nomic_dir")
        normalized = strip_version_prefix(path)

        # Auth: skip for GET (public read-only dashboard data)
        method = getattr(handler, "command", "GET") if handler else "GET"
        if method != "GET":
            user, err = self.require_auth_or_error(handler)
            if err:
                return err
            _, perm_err = self.require_permission_or_error(handler, "debates:write")
            if perm_err:
                return perm_err

        if normalized == "/api/replays":
            if err := self._apply_rate_limit(handler):
                return err
            limit = get_int_param(query_params, "limit", 100)
            return self._list_replays(nomic_dir, max(1, min(limit, 500)))

        if normalized == "/api/learning/evolution":
            if err := self._apply_rate_limit(handler):
                return err
            limit = get_int_param(query_params, "limit", 20)
            return self._get_learning_evolution(nomic_dir, max(1, min(limit, 100)))

        if normalized == "/api/meta-learning/stats":
            if err := self._apply_rate_limit(handler):
                return err
            limit = get_int_param(query_params, "limit", 20)
            return self._get_meta_learning_stats(nomic_dir, max(1, min(limit, 50)))

        if normalized.startswith("/api/replays/"):
            if err := self._apply_rate_limit(handler):
                return err
            # Path: /api/replays/{id} -> split: ["", "api", "replays", "{id}"]
            replay_id, err = self.extract_path_param(normalized, 3, "replay_id")
            if err:
                return err
            # Support pagination for large replay files
            offset = get_int_param(query_params, "offset", 0)
            limit = get_int_param(query_params, "limit", 1000)
            return self._get_replay(nomic_dir, replay_id, max(0, offset), max(1, min(limit, 5000)))

        return None

    @ttl_cache(ttl_seconds=CACHE_TTL_REPLAYS_LIST, key_prefix="replays_list", skip_first=True)
    @handle_errors("replays list retrieval")
    def _list_replays(self, nomic_dir: Path | None, limit: int = 100) -> HandlerResult:
        """List available replay directories with bounded iteration."""
        if not nomic_dir:
            return json_response([])

        replays_dir = nomic_dir / "replays"
        if not replays_dir.exists():
            return json_response([])

        # Collect directory entries with modification times (bounded iteration)
        max_to_scan = limit * 3  # Scan more to account for missing meta.json
        dir_entries: list[tuple[float, Path]] = []

        for replay_path in replays_dir.iterdir():
            if not replay_path.is_dir():
                continue
            try:
                mtime = replay_path.stat().st_mtime
                dir_entries.append((mtime, replay_path))
            except OSError:
                continue
            # Early termination to prevent memory exhaustion
            if len(dir_entries) >= max_to_scan:
                break

        # Sort only the collected subset by modification time (newest first)
        dir_entries.sort(key=lambda x: x[0], reverse=True)

        replays = []
        for _, replay_path in dir_entries[:limit]:
            meta_file = replay_path / "meta.json"
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text())
                    replays.append(
                        {
                            "id": replay_path.name,
                            "topic": meta.get("topic", replay_path.name),
                            "agents": [a.get("name") for a in meta.get("agents", [])],
                            "schema_version": meta.get("schema_version", "1.0"),
                        }
                    )
                except json.JSONDecodeError:
                    # Skip malformed meta files
                    continue

        return json_response(replays)

    @handle_errors("replay retrieval")
    def _get_replay(
        self, nomic_dir: Path | None, replay_id: str, offset: int = 0, limit: int = 1000
    ) -> HandlerResult:
        """Get a specific replay with events (streaming with pagination).

        Args:
            nomic_dir: Base directory for nomic data
            replay_id: ID of the replay to fetch
            offset: Number of events to skip (for pagination)
            limit: Maximum number of events to return

        Returns:
            Replay metadata and paginated events
        """
        if not nomic_dir:
            return error_response("Replays not configured", 503)

        replay_dir = nomic_dir / "replays" / replay_id
        if not replay_dir.exists():
            return error_response(f"Replay not found: {replay_id}", 404)

        # Load meta
        meta_file = replay_dir / "meta.json"
        meta = {}
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text())
            except json.JSONDecodeError:
                meta = {"error": "Failed to parse meta.json"}

        # Stream events with pagination (bounded memory usage)
        events_file = replay_dir / "events.jsonl"
        events: list[dict[str, Any]] = []
        total_events = 0
        if events_file.exists():
            with open(events_file) as f:
                for i, line in enumerate(f):
                    total_events += 1
                    # Skip until we reach offset
                    if i < offset:
                        continue
                    # Stop after limit
                    if len(events) >= limit:
                        continue  # Keep counting total
                    line = line.strip()
                    if line:
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue

        return json_response(
            {
                "id": replay_id,
                "meta": meta,
                "events": events,
                "event_count": len(events),
                "total_events": total_events,
                "offset": offset,
                "limit": limit,
                "has_more": offset + len(events) < total_events,
            }
        )

    @ttl_cache(
        ttl_seconds=CACHE_TTL_LEARNING_EVOLUTION, key_prefix="learning_evolution", skip_first=True
    )
    @handle_errors("learning evolution retrieval")
    def _get_learning_evolution(self, nomic_dir: Path | None, limit: int) -> HandlerResult:
        """Get learning/evolution data from meta_learning.db and elo_snapshot.json.

        Returns data in the format expected by the LearningEvolution frontend:
        - patterns: Issue type success rates over time
        - agents: Agent reputation/acceptance over time
        - debates: Debate statistics over time
        """
        empty_response = {
            "patterns": [],
            "patterns_count": 0,
            "agents": [],
            "agents_count": 0,
            "debates": [],
            "debates_count": 0,
        }

        if not nomic_dir:
            return json_response(empty_response)

        # Collect patterns from meta_learning.db
        patterns: list[dict] = []
        db_path = nomic_dir / "meta_learning.db"
        if db_path.exists():
            try:
                db = MemoryDatabase(str(db_path))
                with db.connection() as conn:
                    conn.row_factory = sqlite3.Row

                    # Get recent patterns, transform for frontend format
                    cursor = conn.execute(
                        """
                        SELECT * FROM meta_patterns
                        ORDER BY created_at DESC
                        LIMIT ?
                    """,
                        (limit,),
                    )
                    for row in cursor.fetchall():
                        row_dict = dict(row)
                        # Transform to frontend expected format
                        patterns.append(
                            {
                                "date": row_dict.get("created_at", "")[:10],  # YYYY-MM-DD
                                "issue_type": row_dict.get("pattern_type", "unknown"),
                                "success_rate": row_dict.get("success_rate", 0.5),
                                "pattern_count": row_dict.get("occurrence_count", 1),
                            }
                        )
            except sqlite3.OperationalError as e:
                if "no such table" not in str(e):
                    raise

        # Collect agent data from ELO snapshot
        agents: list[dict] = []
        elo_path = nomic_dir / "elo_snapshot.json"
        if elo_path.exists():
            try:
                elo_data = json.loads(elo_path.read_text())
                agent_ratings = elo_data.get("ratings", {})
                snapshot_time = (
                    elo_data.get("timestamp", "")[:10] if elo_data.get("timestamp") else ""
                )

                for agent_name, rating in agent_ratings.items():
                    # Calculate acceptance rate from win ratio
                    games = rating.get("games", 0)
                    wins = rating.get("wins", 0)
                    acceptance_rate = wins / games if games > 0 else 0.5

                    agents.append(
                        {
                            "agent": agent_name,
                            "date": snapshot_time,
                            "acceptance_rate": acceptance_rate,
                            "critique_quality": rating.get("calibration_score", 0.5),
                            "reputation_score": min(
                                rating.get("elo", 1000) / 2000, 1.0
                            ),  # Normalize ELO to 0-1
                        }
                    )
            except (json.JSONDecodeError, KeyError) as e:
                logger.debug("Failed to parse ELO snapshot %s: %s", elo_path.name, e)

        # Collect debate data from nomic state history
        debates: list[dict] = []
        state_path = nomic_dir / "nomic_state.json"
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text())
                # Group debates by date
                debate_history = state.get("debate_history", [])
                date_groups: dict[str, list] = {}
                for debate in debate_history[-limit:]:
                    date = debate.get("timestamp", "")[:10]
                    if date:
                        if date not in date_groups:
                            date_groups[date] = []
                        date_groups[date].append(debate)

                for date, day_debates in sorted(date_groups.items()):
                    total = len(day_debates)
                    consensus_count = sum(
                        1 for d in day_debates if d.get("consensus_reached", False)
                    )
                    avg_conf = (
                        sum(d.get("confidence", 0.5) for d in day_debates) / total if total else 0
                    )
                    avg_rounds = (
                        sum(d.get("rounds", DEFAULT_ROUNDS) for d in day_debates) / total
                        if total
                        else DEFAULT_ROUNDS
                    )
                    avg_duration = (
                        sum(d.get("duration_seconds", 60) for d in day_debates) / total
                        if total
                        else 60
                    )

                    debates.append(
                        {
                            "date": date,
                            "total_debates": total,
                            "consensus_rate": consensus_count / total if total else 0,
                            "avg_confidence": avg_conf,
                            "avg_rounds": avg_rounds,
                            "avg_duration": avg_duration,
                        }
                    )
            except (json.JSONDecodeError, KeyError) as e:
                logger.debug("Failed to parse nomic state for debate history: %s", e)

        return json_response(
            {
                "patterns": patterns,
                "patterns_count": len(patterns),
                "agents": agents,
                "agents_count": len(agents),
                "debates": debates,
                "debates_count": len(debates),
            }
        )

    @ttl_cache(
        ttl_seconds=CACHE_TTL_META_LEARNING, key_prefix="meta_learning_stats", skip_first=True
    )
    @handle_errors("meta learning stats retrieval")
    def _get_meta_learning_stats(self, nomic_dir: Path | None, limit: int) -> HandlerResult:
        """Get meta-learning hyperparameters and efficiency stats.

        Returns current hyperparameters, adjustment history, and efficiency metrics.
        """
        if not nomic_dir:
            return json_response(
                {
                    "status": "no_data",
                    "current_hyperparams": {},
                    "adjustment_history": [],
                    "efficiency_log": [],
                }
            )

        db_path = nomic_dir / "meta_learning.db"
        if not db_path.exists():
            return json_response(
                {
                    "status": "no_database",
                    "current_hyperparams": {},
                    "adjustment_history": [],
                    "efficiency_log": [],
                }
            )

        try:
            db = MemoryDatabase(str(db_path))
            with db.connection() as conn:
                conn.row_factory = sqlite3.Row

                # Get current hyperparameters (most recent)
                cursor = conn.execute("""
                    SELECT hyperparams, metrics, adjustment_reason, created_at
                    FROM meta_hyperparams
                    ORDER BY created_at DESC
                    LIMIT 1
                """)
                row = cursor.fetchone()
                current_hyperparams = safe_json_parse(row["hyperparams"], {}) if row else {}

                # Get adjustment history
                cursor = conn.execute(
                    """
                    SELECT hyperparams, metrics, adjustment_reason, created_at
                    FROM meta_hyperparams
                    ORDER BY created_at DESC
                    LIMIT ?
                """,
                    (limit,),
                )
                adjustment_history = [
                    {
                        "hyperparams": safe_json_parse(row["hyperparams"], {}),
                        "metrics": safe_json_parse(row["metrics"]),
                        "reason": row["adjustment_reason"],
                        "timestamp": row["created_at"],
                    }
                    for row in cursor.fetchall()
                ]

                # Get efficiency log
                cursor = conn.execute(
                    """
                    SELECT cycle_number, metrics, created_at
                    FROM meta_efficiency_log
                    ORDER BY created_at DESC
                    LIMIT ?
                """,
                    (limit,),
                )
                efficiency_log = [
                    {
                        "cycle": row["cycle_number"],
                        "metrics": safe_json_parse(row["metrics"], {}),
                        "timestamp": row["created_at"],
                    }
                    for row in cursor.fetchall()
                ]

                # Compute trend from efficiency log
                trend = "insufficient_data"
                if len(efficiency_log) >= 4:
                    mid = len(efficiency_log) // 2
                    first_half = efficiency_log[mid:]  # Older entries (reversed order)
                    second_half = efficiency_log[:mid]  # Newer entries
                    if first_half and second_half:
                        first_retention = sum(
                            e.get("metrics", {}).get("pattern_retention_rate", 0.5)
                            for e in first_half
                        ) / len(first_half)
                        second_retention = sum(
                            e.get("metrics", {}).get("pattern_retention_rate", 0.5)
                            for e in second_half
                        ) / len(second_half)
                        if second_retention > first_retention + 0.05:
                            trend = "improving"
                        elif second_retention < first_retention - 0.05:
                            trend = "declining"
                        else:
                            trend = "stable"

            return json_response(
                {
                    "status": "ok",
                    "current_hyperparams": current_hyperparams,
                    "adjustment_history": adjustment_history,
                    "efficiency_log": efficiency_log,
                    "trend": trend,
                    "evaluations": len(efficiency_log),
                }
            )
        except sqlite3.OperationalError as e:
            # Table may not exist yet
            if "no such table" in str(e):
                return json_response(
                    {
                        "status": "tables_not_initialized",
                        "current_hyperparams": {},
                        "adjustment_history": [],
                        "efficiency_log": [],
                    }
                )
            raise
