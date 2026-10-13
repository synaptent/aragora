"""System Intelligence Dashboard Handler.

Aggregates data from multiple subsystems to provide a unified view
of the system's learning, agent performance, institutional memory,
and improvement queue state.

Endpoints:
- GET /api/v1/system-intelligence/overview          - High-level system stats
- GET /api/v1/system-intelligence/agent-performance  - ELO, calibration, win rates
- GET /api/v1/system-intelligence/institutional-memory - Cross-debate injection stats
- GET /api/v1/system-intelligence/improvement-queue   - Queue contents + breakdown
- GET /api/v1/system-intelligence/anomalies          - Recent anomaly alerts
- GET /api/v1/system-intelligence/events             - Recent system events
- GET /api/v1/system-intelligence/km-sync            - Knowledge sync status
- GET /api/v1/system-intelligence/nomic-status       - Nomic loop status
- GET /api/v1/system-intelligence/debate-queue       - Debate activity summary
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from aragora.server.versioning.compat import strip_version_prefix
from aragora.server.validation.query_params import safe_query_int

from ..base import (
    HandlerResult,
    json_response,
)
from ..secure import SecureHandler
from ..utils.auth_mixins import SecureEndpointMixin
from ..utils.rate_limit import rate_limit

logger = logging.getLogger(__name__)


async def _maybe_await(value: Any) -> Any:
    """Await value when it is a coroutine, otherwise return as-is."""
    if asyncio.iscoroutine(value):
        return await value
    return value


class SystemIntelligenceHandler(SecureEndpointMixin, SecureHandler):  # type: ignore[misc]
    """Handler for the system intelligence dashboard.

    Aggregates ELO rankings, calibration data, Nomic cycle stats,
    selection feedback, and Knowledge Mound counts into a single
    dashboard view.

    RBAC Permissions:
    - system_intelligence:read - View all intelligence endpoints
    """

    RESOURCE_TYPE = "system_intelligence"

    ROUTES = [
        "/api/system-intelligence/overview",
        "/api/system-intelligence/agent-performance",
        "/api/system-intelligence/institutional-memory",
        "/api/system-intelligence/improvement-queue",
        "/api/system-intelligence/anomalies",
        "/api/system-intelligence/events",
        "/api/system-intelligence/km-sync",
        "/api/system-intelligence/nomic-status",
        "/api/system-intelligence/debate-queue",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can handle the given path."""
        path = strip_version_prefix(path)
        return path in self.ROUTES

    @rate_limit(requests_per_minute=30)
    async def handle(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route GET requests to the appropriate endpoint."""
        path = strip_version_prefix(path)

        handlers = {
            "/api/system-intelligence/overview": self._get_overview,
            "/api/system-intelligence/agent-performance": self._get_agent_performance,
            "/api/system-intelligence/institutional-memory": self._get_institutional_memory,
            "/api/system-intelligence/improvement-queue": self._get_improvement_queue,
            "/api/system-intelligence/anomalies": self._get_anomalies,
            "/api/system-intelligence/events": lambda: self._get_events(query_params),
            "/api/system-intelligence/km-sync": self._get_km_sync,
            "/api/system-intelligence/nomic-status": self._get_nomic_status,
            "/api/system-intelligence/debate-queue": self._get_debate_queue,
        }

        endpoint_handler = handlers.get(path)
        if endpoint_handler:
            return await endpoint_handler()

        return None

    # ------------------------------------------------------------------
    # GET /api/v1/system-intelligence/overview
    # ------------------------------------------------------------------

    async def _get_overview(self) -> HandlerResult:
        """High-level system intelligence overview.

        Returns:
            {"data": {
                "totalCycles": int,
                "successRate": float,
                "activeAgents": int,
                "knowledgeItems": int,
                "topAgents": [...],
                "recentImprovements": [...]
            }}
        """
        total_cycles = 0
        success_rate = 0.0
        active_agents = 0
        knowledge_items = 0
        top_agents: list[dict[str, Any]] = []
        recent_improvements: list[dict[str, Any]] = []

        # Nomic cycle stats
        try:
            from aragora.nomic.cycle_store import get_cycle_store

            store = get_cycle_store()
            recent_cycles: list[Any] = []
            recent_cycles_getter = getattr(store, "get_recent_cycles", None)
            if callable(recent_cycles_getter):
                recent_candidate = recent_cycles_getter(50)
                if isinstance(recent_candidate, list):
                    recent_cycles = recent_candidate

            if not recent_cycles:
                recent_getter = getattr(store, "get_recent", None)
                if callable(recent_getter):
                    recent_candidate = recent_getter(limit=50)
                    if isinstance(recent_candidate, list):
                        recent_cycles = recent_candidate

            total_cycles = len(recent_cycles)
            successes = 0
            for cycle in recent_cycles:
                if isinstance(cycle, dict):
                    is_success = bool(cycle.get("success", False))
                else:
                    is_success = bool(getattr(cycle, "success", False))
                if is_success:
                    successes += 1
            if total_cycles > 0:
                success_rate = round(successes / total_cycles, 4)
        except (ImportError, RuntimeError, ValueError, OSError, AttributeError):
            logger.debug("CycleStore not available for overview")

        # ELO leaderboard for top agents
        try:
            from aragora.ranking.elo import EloSystem

            elo = EloSystem()
            leaderboard = elo.get_leaderboard(limit=10)
            for rating in leaderboard:
                if isinstance(rating, dict):
                    agent_id = rating.get("agent_name", "")
                    elo_score = rating.get("elo", rating.get("rating", 1500))
                    wins = rating.get("wins", 0)
                else:
                    agent_id = getattr(rating, "agent_name", "")
                    elo_score = getattr(rating, "elo", getattr(rating, "rating", 1500))
                    wins = getattr(rating, "wins", 0)
                top_agents.append(
                    {
                        "id": agent_id,
                        "elo": elo_score,
                        "wins": wins,
                    }
                )
            active_agents = len(leaderboard)
        except (ImportError, RuntimeError, ValueError, OSError, AttributeError):
            logger.debug("EloSystem not available for overview")

        # Knowledge Mound item count
        try:
            from aragora.knowledge.mound.core import KnowledgeMoundCore

            km = KnowledgeMoundCore()
            get_stats = getattr(km, "get_stats", None)
            stats: Any = await _maybe_await(get_stats()) if callable(get_stats) else {}
            if isinstance(stats, dict):
                raw_items: Any = stats.get("total_items", stats.get("total_nodes", 0))
                knowledge_items = int(raw_items)
            else:
                knowledge_items = int(getattr(stats, "total_nodes", 0))
        except (ImportError, RuntimeError, ValueError, OSError, AttributeError):
            logger.debug("KnowledgeMound not available for overview")

        # Recent improvement queue items
        try:
            from aragora.nomic.improvement_queue import get_improvement_queue

            queue = get_improvement_queue()
            for s in queue.peek(5):
                recent_improvements.append(
                    {
                        "id": s.debate_id,
                        "goal": s.task[:200],
                        "status": s.category,
                    }
                )
        except (ImportError, RuntimeError):
            pass

        return json_response(
            {
                "data": {
                    "totalCycles": total_cycles,
                    "successRate": success_rate,
                    "activeAgents": active_agents,
                    "knowledgeItems": knowledge_items,
                    "topAgents": top_agents,
                    "recentImprovements": recent_improvements,
                }
            }
        )

    # ------------------------------------------------------------------
    # GET /api/v1/system-intelligence/agent-performance
    # ------------------------------------------------------------------

    async def _get_agent_performance(self) -> HandlerResult:
        """Agent performance details: ELO history, calibration, win rates.

        Returns:
            {"data": {"agents": [...]}}
        """
        agents: list[dict[str, Any]] = []

        # ELO data
        try:
            from aragora.ranking.elo import EloSystem

            elo = EloSystem()
            leaderboard = elo.get_leaderboard(limit=50)

            for entry in leaderboard:
                if isinstance(entry, dict):
                    name = entry.get("agent_name", "")
                    rating = entry.get("elo", entry.get("rating", 1500))
                    wins = entry.get("wins", 0)
                    losses = entry.get("losses", 0)
                else:
                    name = getattr(entry, "agent_name", "")
                    rating = getattr(entry, "elo", getattr(entry, "rating", 1500))
                    wins = getattr(entry, "wins", 0)
                    losses = getattr(entry, "losses", 0)

                total = wins + losses
                win_rate = round(wins / total, 4) if total > 0 else 0.0

                # ELO history
                elo_history: list[dict[str, Any]] = []
                try:
                    get_agent_history = getattr(elo, "get_agent_history", None)
                    if callable(get_agent_history):
                        history = get_agent_history(name, limit=20)
                        for history_entry in history:
                            if isinstance(history_entry, dict):
                                elo_history.append(
                                    {
                                        "date": history_entry.get("timestamp", ""),
                                        "elo": history_entry.get("rating", rating),
                                    }
                                )
                            else:
                                elo_history.append(
                                    {
                                        "date": getattr(history_entry, "timestamp", ""),
                                        "elo": getattr(history_entry, "rating", rating),
                                    }
                                )
                    else:
                        history = elo.get_elo_history(name, limit=20)
                        for ts, elo_value in history:
                            elo_history.append(
                                {
                                    "date": ts,
                                    "elo": elo_value,
                                }
                            )
                except (AttributeError, TypeError, ValueError):
                    pass

                # Calibration score
                calibration = 0.0
                try:
                    get_calibration_score = getattr(elo, "get_calibration_score", None)
                    if callable(get_calibration_score):
                        cal_data = get_calibration_score(name)
                        if isinstance(cal_data, (int, float)):
                            calibration = float(cal_data)
                        elif isinstance(cal_data, dict):
                            calibration = float(cal_data.get("score", 0.0))
                    else:
                        calibration = float(elo.get_rating(name).calibration_score)
                except (AttributeError, TypeError, ValueError):
                    pass

                # Domain performance from SelectionFeedbackLoop
                domains: list[str] = []
                try:
                    from aragora.debate.selection_feedback import SelectionFeedbackLoop

                    feedback = SelectionFeedbackLoop()
                    state = feedback.get_agent_state(name)
                    if state:
                        domains = list(state.domain_wins.keys())
                except (ImportError, AttributeError, TypeError):
                    pass

                agents.append(
                    {
                        "id": name,
                        "name": name,
                        "elo": rating,
                        "eloHistory": elo_history,
                        "calibration": calibration,
                        "winRate": win_rate,
                        "domains": domains,
                    }
                )

        except (ImportError, RuntimeError, ValueError, OSError, AttributeError):
            logger.debug("EloSystem not available for agent performance")

        return json_response({"data": {"agents": agents}})

    # ------------------------------------------------------------------
    # GET /api/v1/system-intelligence/institutional-memory
    # ------------------------------------------------------------------

    async def _get_institutional_memory(self) -> HandlerResult:
        """Cross-debate injection stats and knowledge patterns.

        Returns:
            {"data": {
                "totalInjections": int,
                "retrievalCount": int,
                "topPatterns": [...],
                "confidenceChanges": [...]
            }}
        """
        total_injections = 0
        retrieval_count = 0
        top_patterns: list[dict[str, Any]] = []
        confidence_changes: list[dict[str, Any]] = []

        # NomicCycleAdapter for pattern data
        try:
            from aragora.knowledge.mound.adapters.nomic_cycle_adapter import (
                get_nomic_cycle_adapter,
            )

            adapter = get_nomic_cycle_adapter()

            # High-ROI patterns double as "top patterns"
            try:
                roi_data = await adapter.find_high_roi_goal_types(limit=10)
                for entry in roi_data:
                    top_patterns.append(
                        {
                            "pattern": entry.get("pattern", ""),
                            "frequency": entry.get("cycle_count", 0),
                            "confidence": entry.get("avg_improvement_score", 0.0),
                        }
                    )
            except (RuntimeError, ValueError, OSError, AttributeError):
                pass

        except (ImportError, RuntimeError, ValueError, OSError):
            logger.debug("NomicCycleAdapter not available for institutional memory")

        # Cross-debate memory stats
        try:
            from aragora.memory.cross_debate_rlm import CrossDebateMemory

            cdm = CrossDebateMemory()
            stats_getter = getattr(cdm, "get_statistics", None)
            stats: Any = {}
            if callable(stats_getter):
                stats = stats_getter()
            if not isinstance(stats, dict):
                legacy_stats_getter = getattr(cdm, "get_stats", None)
                stats = legacy_stats_getter() if callable(legacy_stats_getter) else {}
            if isinstance(stats, dict):
                raw_injections: Any = stats.get("total_injections", stats.get("total_entries", 0))
                raw_retrievals: Any = stats.get("retrieval_count", stats.get("total_tokens", 0))
                total_injections = int(raw_injections)
                retrieval_count = int(raw_retrievals)
        except (ImportError, RuntimeError, AttributeError):
            logger.debug("CrossDebateMemory not available")

        # Confidence changes from Knowledge Mound
        try:
            from aragora.knowledge.mound.core import KnowledgeMoundCore

            km = KnowledgeMoundCore()
            decay_getter = getattr(km, "get_confidence_decay_stats", None)
            if callable(decay_getter):
                decay_stats = await _maybe_await(decay_getter())
                if isinstance(decay_stats, list):
                    for entry in decay_stats[:10]:
                        if isinstance(entry, dict):
                            confidence_changes.append(
                                {
                                    "topic": entry.get("topic", ""),
                                    "before": entry.get("initial_confidence", 0.0),
                                    "after": entry.get("current_confidence", 0.0),
                                }
                            )
            else:
                get_stats = getattr(km, "get_stats", None)
                mound_stats: Any = await _maybe_await(get_stats()) if callable(get_stats) else None
                if mound_stats is not None and hasattr(mound_stats, "average_confidence"):
                    confidence_changes.append(
                        {
                            "topic": "global",
                            "before": float(getattr(mound_stats, "average_confidence", 0.0)),
                            "after": float(getattr(mound_stats, "average_confidence", 0.0)),
                        }
                    )
        except (ImportError, RuntimeError, AttributeError):
            logger.debug("KM confidence decay stats not available")

        return json_response(
            {
                "data": {
                    "totalInjections": total_injections,
                    "retrievalCount": retrieval_count,
                    "topPatterns": top_patterns,
                    "confidenceChanges": confidence_changes,
                }
            }
        )

    # ------------------------------------------------------------------
    # GET /api/v1/system-intelligence/improvement-queue
    # ------------------------------------------------------------------

    async def _get_improvement_queue(self) -> HandlerResult:
        """Improvement queue contents with source breakdown.

        Returns:
            {"data": {
                "items": [...],
                "totalSize": int,
                "sourceBreakdown": {"debate": N, "user": N, ...}
            }}
        """
        items: list[dict[str, Any]] = []
        total_size = 0
        source_breakdown: dict[str, int] = {}

        try:
            from aragora.nomic.improvement_queue import get_improvement_queue

            queue = get_improvement_queue()
            total_size = len(queue)

            for s in queue.peek(50):
                items.append(
                    {
                        "id": s.debate_id,
                        "goal": s.task[:200],
                        "priority": int(s.confidence * 100),
                        "source": s.category,
                        "status": "pending",
                        "createdAt": str(s.created_at),
                    }
                )
                source_breakdown[s.category] = source_breakdown.get(s.category, 0) + 1

        except (ImportError, RuntimeError):
            logger.debug("ImprovementQueue not available")

        return json_response(
            {
                "data": {
                    "items": items,
                    "totalSize": total_size,
                    "sourceBreakdown": source_breakdown,
                }
            }
        )

    # ------------------------------------------------------------------
    # GET /api/v1/system-intelligence/anomalies
    # ------------------------------------------------------------------

    async def _get_anomalies(self) -> HandlerResult:
        """Recent anomaly alerts formatted for the dashboard."""
        alerts: list[dict[str, Any]] = []

        try:
            from aragora.security.anomaly_detection import get_anomaly_detector

            detector = get_anomaly_detector()
            recent = detector.get_recent_anomalies(hours=24)

            for idx, anomaly in enumerate(recent[:50]):
                if not isinstance(anomaly, dict):
                    continue

                raw_severity = str(anomaly.get("severity", "info")).lower()
                if raw_severity == "critical":
                    severity = "critical"
                elif raw_severity in {"warning", "high", "medium", "low"}:
                    severity = "warning"
                else:
                    severity = "info"

                source = str(anomaly.get("anomaly_type") or anomaly.get("source") or "anomaly")
                message = str(anomaly.get("description") or anomaly.get("message") or source)

                alerts.append(
                    {
                        "id": str(anomaly.get("id") or f"anomaly-{idx}"),
                        "severity": severity,
                        "message": message,
                        "source": source,
                        "timestamp": str(
                            anomaly.get("timestamp") or datetime.now(timezone.utc).isoformat()
                        ),
                        "resolved": bool(anomaly.get("resolved", False)),
                    }
                )
        except (ImportError, RuntimeError, ValueError, OSError, AttributeError, TypeError) as e:
            logger.debug("Anomaly detector not available for system intelligence: %s", e)

        return json_response({"data": {"alerts": alerts}})

    # ------------------------------------------------------------------
    # GET /api/v1/system-intelligence/events
    # ------------------------------------------------------------------

    async def _get_events(self, query_params: dict[str, Any]) -> HandlerResult:
        """Recent system events normalized for the dashboard timeline."""
        limit = safe_query_int(query_params, "limit", default=30, min_val=1, max_val=100)
        events: list[dict[str, Any]] = []

        nomic_dir = self.get_nomic_dir()
        if nomic_dir:
            events_file = nomic_dir / "events.json"
            try:
                if events_file.exists():
                    with open(events_file) as f:
                        raw_events = json.load(f)
                    if isinstance(raw_events, list):
                        for idx, raw in enumerate(raw_events[:limit]):
                            if not isinstance(raw, dict):
                                continue
                            event_data = raw.get("event_data")
                            if not isinstance(event_data, dict):
                                raw_data = raw.get("data")
                                event_data = raw_data if isinstance(raw_data, dict) else {}

                            event_type = str(raw.get("event_type") or raw.get("type") or "event")
                            source = str(
                                raw.get("source")
                                or raw.get("agent")
                                or event_data.get("source")
                                or event_type
                            )
                            message = str(
                                raw.get("message")
                                or raw.get("summary")
                                or raw.get("description")
                                or event_data.get("message")
                                or event_data.get("summary")
                                or event_data.get("title")
                                or event_type.replace("_", " ")
                            )
                            timestamp = str(
                                raw.get("timestamp")
                                or raw.get("created_at")
                                or event_data.get("timestamp")
                                or datetime.now(timezone.utc).isoformat()
                            )

                            events.append(
                                {
                                    "id": str(
                                        raw.get("id") or raw.get("event_id") or f"event-{idx}"
                                    ),
                                    "type": event_type,
                                    "message": message,
                                    "timestamp": timestamp,
                                    "source": source,
                                }
                            )
            except (OSError, ValueError, TypeError) as e:
                logger.debug("System intelligence events unavailable: %s", e)

        return json_response({"data": {"events": events}})

    # ------------------------------------------------------------------
    # GET /api/v1/system-intelligence/km-sync
    # ------------------------------------------------------------------

    async def _get_km_sync(self) -> HandlerResult:
        """Knowledge Mound sync snapshot for the dashboard."""
        last_sync: str | None = None
        pending_items = 0
        adapters_active = 0
        adapters_total = 0
        sync_healthy = False

        try:
            from aragora.server.handlers.admin.system_health import SystemHealthDashboardHandler

            adapter_snapshot = SystemHealthDashboardHandler(self.ctx)._collect_adapters()
            adapters_active = int(adapter_snapshot.get("active", 0))
            adapters_total = int(adapter_snapshot.get("total", 0))
            sync_healthy = bool(adapter_snapshot.get("available", False))
        except (ImportError, RuntimeError, ValueError, OSError, AttributeError, TypeError) as e:
            logger.debug("KM adapter snapshot unavailable: %s", e)

        try:
            from aragora.knowledge.mound.ops.federation_scheduler import get_federation_scheduler

            scheduler = get_federation_scheduler()
            stats = scheduler.get_stats()
            history = scheduler.get_history(limit=1)

            if history:
                started_at: Any = getattr(history[0], "started_at", None)
                if hasattr(started_at, "isoformat"):
                    last_sync = started_at.isoformat()

            if isinstance(stats, dict):
                recent = stats.get("recent", {})
                if isinstance(recent, dict) and int(recent.get("total", 0)) > 0:
                    sync_healthy = sync_healthy and float(recent.get("success_rate", 0.0)) >= 0.5
        except (ImportError, RuntimeError, ValueError, OSError, AttributeError, TypeError) as e:
            logger.debug("KM federation scheduler unavailable: %s", e)

        return json_response(
            {
                "data": {
                    "last_sync": last_sync,
                    "pending_items": pending_items,
                    "adapters_active": adapters_active,
                    "adapters_total": adapters_total,
                    "sync_healthy": sync_healthy,
                }
            }
        )

    # ------------------------------------------------------------------
    # GET /api/v1/system-intelligence/nomic-status
    # ------------------------------------------------------------------

    async def _get_nomic_status(self) -> HandlerResult:
        """Condensed Nomic loop status used by the live dashboard."""
        active = False
        current_cycle = 0
        current_phase = "idle"
        last_completed_at: str | None = None
        success_rate = 0.0
        total_cycles = 0

        nomic_dir = self.get_nomic_dir()
        if nomic_dir:
            state_file = nomic_dir / "nomic_state.json"
            try:
                if state_file.exists():
                    with open(state_file) as f:
                        state = json.load(f)
                    if isinstance(state, dict):
                        active = bool(
                            state.get("running")
                            or str(state.get("status", "")).lower() == "running"
                        )
                        current_cycle = int(state.get("current_cycle", 0) or 0)
                        current_phase = str(
                            state.get("phase")
                            or state.get("current_phase")
                            or current_phase
                            or "idle"
                        )
            except (OSError, ValueError, TypeError) as e:
                logger.debug("Nomic state file unavailable: %s", e)

        try:
            from aragora.nomic.cycle_store import get_cycle_store

            store = get_cycle_store()
            recent_cycles = store.get_recent_cycles(100)
            total_cycles = len(recent_cycles)
            if total_cycles > 0:
                success_count = 0
                completed_timestamps: list[float] = []

                for cycle in recent_cycles:
                    cycle_success = (
                        bool(cycle.get("success", False))
                        if isinstance(cycle, dict)
                        else bool(getattr(cycle, "success", False))
                    )
                    if cycle_success:
                        success_count += 1

                    completed_at = (
                        cycle.get("completed_at")
                        if isinstance(cycle, dict)
                        else getattr(cycle, "completed_at", None)
                    )
                    if isinstance(completed_at, (int, float)):
                        completed_timestamps.append(float(completed_at))

                success_rate = round(success_count / total_cycles, 4)
                if completed_timestamps:
                    last_completed_at = datetime.fromtimestamp(
                        max(completed_timestamps), tz=timezone.utc
                    ).isoformat()
                if current_cycle == 0:
                    current_cycle = total_cycles + (1 if active else 0)
        except (ImportError, RuntimeError, ValueError, OSError, AttributeError, TypeError) as e:
            logger.debug("Nomic cycle store unavailable: %s", e)

        return json_response(
            {
                "data": {
                    "active": active,
                    "current_cycle": current_cycle,
                    "current_phase": current_phase,
                    "last_completed_at": last_completed_at,
                    "success_rate": success_rate,
                    "total_cycles": total_cycles,
                }
            }
        )

    # ------------------------------------------------------------------
    # GET /api/v1/system-intelligence/debate-queue
    # ------------------------------------------------------------------

    async def _get_debate_queue(self) -> HandlerResult:
        """Debate activity summary from active state and batch queue."""
        active_debates = 0
        queued_debates = 0
        completed_today = 0
        avg_duration_ms = 0.0

        try:
            from aragora.server.state import get_state_manager

            state_stats = get_state_manager().get_stats()
            active_debates = int(state_stats.get("active_debates", 0))
        except (ImportError, RuntimeError, ValueError, OSError, AttributeError, TypeError) as e:
            logger.debug("State manager unavailable for debate queue: %s", e)

        try:
            from aragora.server.debate_queue import get_debate_queue_sync

            queue = get_debate_queue_sync()
            if queue is not None:
                active_debates = max(active_debates, int(getattr(queue, "_active_count", 0)))
                today = datetime.now(timezone.utc).date()
                completed_durations: list[float] = []

                for batch in getattr(queue, "_batches", {}).values():
                    for item in getattr(batch, "items", []):
                        status_value = getattr(item, "status", "")
                        if hasattr(status_value, "value"):
                            status_value = status_value.value
                        status = str(status_value).lower()

                        if status == "queued":
                            queued_debates += 1

                        completed_at = getattr(item, "completed_at", None)
                        started_at = getattr(item, "started_at", None)
                        if status == "completed" and isinstance(completed_at, (int, float)):
                            completed_date = datetime.fromtimestamp(
                                float(completed_at), tz=timezone.utc
                            ).date()
                            if completed_date == today:
                                completed_today += 1
                            if isinstance(started_at, (int, float)):
                                completed_durations.append(
                                    max(0.0, (float(completed_at) - float(started_at)) * 1000)
                                )

                if completed_durations:
                    avg_duration_ms = round(sum(completed_durations) / len(completed_durations), 1)
        except (ImportError, RuntimeError, ValueError, OSError, AttributeError, TypeError) as e:
            logger.debug("Debate queue unavailable for system intelligence: %s", e)

        return json_response(
            {
                "data": {
                    "active_debates": active_debates,
                    "queued_debates": queued_debates,
                    "completed_today": completed_today,
                    "avg_duration_ms": avg_duration_ms,
                }
            }
        )
