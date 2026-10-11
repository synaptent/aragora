"""
Confidence Decay Scheduler for Knowledge Mound.

Provides automatic confidence decay for aging knowledge items:
- Periodic background decay application
- Configurable decay intervals per workspace
- Integration with control plane for distributed scheduling
- Event emission for monitoring

Usage:
    from aragora.knowledge.mound.confidence_decay_scheduler import ConfidenceDecayScheduler

    scheduler = ConfidenceDecayScheduler(
        knowledge_mound=mound,
        decay_interval_hours=24,
    )

    # Start background decay
    await scheduler.start()

    # Manual trigger
    await scheduler.apply_decay_to_workspaces()

    # Stop scheduler
    await scheduler.stop()
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.knowledge.mound.facade import KnowledgeMound

logger = logging.getLogger(__name__)

# Check if Prometheus metrics are available
try:
    from prometheus_client import Counter  # noqa: F401

    DECAY_METRICS_AVAILABLE = True
except ImportError:
    DECAY_METRICS_AVAILABLE = False

# Prometheus metrics for monitoring decay operations
_DECAY_CYCLES: Any = None
_DECAY_ITEMS_PROCESSED: Any = None
_DECAY_ITEMS_DECAYED: Any = None
_DECAY_DURATION_SECONDS: Any = None
_DECAY_AVG_CHANGE: Any = None


def _init_decay_metrics() -> bool:
    """Initialize Prometheus metrics for confidence decay. Returns True if successful."""
    global _DECAY_CYCLES, _DECAY_ITEMS_PROCESSED, _DECAY_ITEMS_DECAYED
    global _DECAY_DURATION_SECONDS, _DECAY_AVG_CHANGE

    if _DECAY_CYCLES is not None:
        return True

    try:
        from prometheus_client import Counter, Gauge, Histogram

        _DECAY_CYCLES = Counter(
            "aragora_knowledge_decay_cycles_total",
            "Total confidence decay cycles completed",
            ["workspace"],
        )
        _DECAY_ITEMS_PROCESSED = Counter(
            "aragora_knowledge_decay_items_processed_total",
            "Total items processed by confidence decay",
            ["workspace"],
        )
        _DECAY_ITEMS_DECAYED = Counter(
            "aragora_knowledge_decay_items_decayed_total",
            "Total items that had confidence reduced",
            ["workspace"],
        )
        _DECAY_DURATION_SECONDS = Histogram(
            "aragora_knowledge_decay_duration_seconds",
            "Duration of decay operations",
            ["workspace"],
            buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
        )
        _DECAY_AVG_CHANGE = Gauge(
            "aragora_knowledge_decay_avg_change",
            "Average confidence change in last decay cycle",
            ["workspace"],
        )
        return True
    except ImportError:
        logger.debug("prometheus_client not installed - decay metrics disabled")
        return False


def record_decay_metrics(report: DecayScheduleReport) -> None:
    """Record Prometheus metrics for a decay operation."""
    if not _init_decay_metrics():
        return

    workspace = report.workspace_id or "default"
    _DECAY_CYCLES.labels(workspace=workspace).inc()
    _DECAY_ITEMS_PROCESSED.labels(workspace=workspace).inc(report.items_processed)
    _DECAY_ITEMS_DECAYED.labels(workspace=workspace).inc(report.items_decayed)
    _DECAY_DURATION_SECONDS.labels(workspace=workspace).observe(report.duration_ms / 1000)
    _DECAY_AVG_CHANGE.labels(workspace=workspace).set(report.average_change)


@dataclass
class DecayScheduleReport:
    """Report of a scheduled decay run."""

    workspace_id: str
    items_processed: int
    items_decayed: int
    items_boosted: int
    average_change: float
    duration_ms: float
    scheduled_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "workspace_id": self.workspace_id,
            "items_processed": self.items_processed,
            "items_decayed": self.items_decayed,
            "items_boosted": self.items_boosted,
            "average_change": self.average_change,
            "duration_ms": self.duration_ms,
            "scheduled_at": self.scheduled_at.isoformat(),
        }


class ConfidenceDecayScheduler:
    """
    Background scheduler for automatic confidence decay.

    Monitors Knowledge Mound workspaces and applies time-based
    confidence decay to aging knowledge items.

    Attributes:
        knowledge_mound: Knowledge Mound instance to process
        decay_interval_hours: Hours between decay cycles (default: 24)
        workspaces: Optional list of workspaces to process (default: all)
        max_items_per_workspace: Max items to process per workspace per cycle
        on_decay_complete: Callback when decay completes
    """

    def __init__(
        self,
        knowledge_mound: KnowledgeMound | None = None,
        decay_interval_hours: int = 24,
        workspaces: list[str] | None = None,
        max_items_per_workspace: int = 10000,
        on_decay_complete: Callable[[DecayScheduleReport], None] | None = None,
    ):
        """
        Initialize the confidence decay scheduler.

        Args:
            knowledge_mound: Knowledge Mound instance to process
            decay_interval_hours: Interval between decay cycles (default: 24)
            workspaces: Optional list of workspace IDs to process
            max_items_per_workspace: Max items per workspace per cycle
            on_decay_complete: Callback when decay completes for a workspace
        """
        self._knowledge_mound = knowledge_mound
        self._decay_interval_hours = decay_interval_hours
        self._workspaces = workspaces
        self._max_items_per_workspace = max_items_per_workspace
        self._on_decay_complete = on_decay_complete

        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._last_run: dict[str, datetime] = {}
        self._total_decay_cycles = 0
        self._total_items_processed = 0

    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running

    async def start(self) -> None:
        """Start the background decay scheduler."""
        if self._running:
            logger.warning("ConfidenceDecayScheduler already running")
            return

        if not self._knowledge_mound:
            logger.warning("Cannot start ConfidenceDecayScheduler: no knowledge_mound configured")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "ConfidenceDecayScheduler started: interval=%sh, workspaces=%s",
            self._decay_interval_hours,
            self._workspaces or "all",
        )

    async def stop(self) -> None:
        """Stop the background decay scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("ConfidenceDecayScheduler stopped")

    async def _run_loop(self) -> None:
        """Main background loop."""
        interval_seconds = self._decay_interval_hours * 3600

        while self._running:
            try:
                reports = await self.apply_decay_to_workspaces()
                self._total_decay_cycles += 1

                total_processed = sum(r.items_processed for r in reports)
                total_decayed = sum(r.items_decayed for r in reports)
                self._total_items_processed += total_processed

                logger.info(
                    "Decay cycle %s complete: %s items processed, %s decayed",
                    self._total_decay_cycles,
                    total_processed,
                    total_decayed,
                )

            except (RuntimeError, ConnectionError, TimeoutError) as e:
                logger.warning("Decay cycle failed: %s", e)
            except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
                logger.exception("Unexpected decay cycle error: %s", e)

            # Wait for next cycle
            await asyncio.sleep(interval_seconds)

    async def apply_decay_to_workspaces(
        self,
        force: bool = False,
    ) -> list[DecayScheduleReport]:
        """
        Apply confidence decay to all configured workspaces.

        Args:
            force: Force decay even if recently run

        Returns:
            List of DecayScheduleReport for each workspace
        """
        if not self._knowledge_mound:
            return []

        reports: list[DecayScheduleReport] = []

        # Get workspaces to process
        workspaces = self._workspaces
        if not workspaces:
            # Try to get all workspaces from the mound
            try:
                if hasattr(self._knowledge_mound, "list_workspaces"):
                    workspaces = await self._knowledge_mound.list_workspaces()
                else:
                    # Default to "default" workspace
                    workspaces = ["default"]
            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                logger.warning("Could not list workspaces: %s", e)
                workspaces = ["default"]

        for workspace_id in workspaces:
            try:
                report = await self._apply_decay_to_workspace(workspace_id, force)
                if report:
                    reports.append(report)

                    # Record Prometheus metrics
                    record_decay_metrics(report)

                    if self._on_decay_complete:
                        self._on_decay_complete(report)

            except (RuntimeError, ValueError, KeyError) as e:
                logger.warning("Decay failed for workspace %s: %s", workspace_id, e)
            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                logger.exception("Unexpected decay error for workspace %s: %s", workspace_id, e)

        return reports

    async def _apply_decay_to_workspace(
        self,
        workspace_id: str,
        force: bool = False,
    ) -> DecayScheduleReport | None:
        """
        Apply confidence decay to a single workspace.

        Args:
            workspace_id: Workspace to process
            force: Force decay even if recently run

        Returns:
            DecayScheduleReport or None if skipped
        """
        if not self._knowledge_mound:
            return None

        # Check if decay is needed
        if not force:
            last_run = self._last_run.get(workspace_id)
            if last_run:
                hours_since = (datetime.now() - last_run).total_seconds() / 3600
                if hours_since < self._decay_interval_hours:
                    logger.debug(
                        "Skipping decay for %s, last run %.1fh ago", workspace_id, hours_since
                    )
                    return None

        try:
            # Use the KnowledgeMound's apply_confidence_decay method
            # Note: Uses ConfidenceDecayMixin.apply_confidence_decay (returns DecayReport)
            # not PruningOperationsMixin.apply_confidence_decay (returns int)
            from aragora.knowledge.mound.ops.confidence_decay import DecayReport as DR

            decay_report = cast(
                DR,
                await self._knowledge_mound.apply_confidence_decay(
                    workspace_id=workspace_id,
                    force=force,
                ),
            )

            # Validate decay_report has expected attributes
            required_attrs = [
                "items_processed",
                "items_decayed",
                "items_boosted",
                "average_confidence_change",
                "duration_ms",
            ]
            for attr in required_attrs:
                if not hasattr(decay_report, attr):
                    logger.warning(
                        "Decay report missing attribute '%s' for workspace %s", attr, workspace_id
                    )
                    return None

            # Record run time
            self._last_run[workspace_id] = datetime.now()

            return DecayScheduleReport(
                workspace_id=workspace_id,
                items_processed=decay_report.items_processed,
                items_decayed=decay_report.items_decayed,
                items_boosted=decay_report.items_boosted,
                average_change=decay_report.average_confidence_change,
                duration_ms=decay_report.duration_ms,
            )

        except AttributeError:
            # apply_confidence_decay not available on this mound instance
            logger.warning("apply_confidence_decay not available for workspace %s", workspace_id)
            return None
        except (RuntimeError, ValueError, KeyError) as e:
            logger.warning("Decay application failed for %s: %s", workspace_id, e)
            return None
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.exception("Unexpected decay error for %s: %s", workspace_id, e)
            return None

    async def trigger_decay_now(
        self,
        workspace_id: str | None = None,
    ) -> list[DecayScheduleReport]:
        """
        Trigger immediate decay application.

        Args:
            workspace_id: Optional specific workspace, or all if None

        Returns:
            List of DecayScheduleReport
        """
        if workspace_id:
            report = await self._apply_decay_to_workspace(workspace_id, force=True)
            return [report] if report else []
        else:
            return await self.apply_decay_to_workspaces(force=True)

    def get_stats(self) -> dict[str, Any]:
        """
        Get scheduler statistics.

        Returns:
            Dict with scheduler status and metrics
        """
        return {
            "running": self._running,
            "decay_interval_hours": self._decay_interval_hours,
            "workspaces": self._workspaces,
            "max_items_per_workspace": self._max_items_per_workspace,
            "total_decay_cycles": self._total_decay_cycles,
            "total_items_processed": self._total_items_processed,
            "last_run": {k: v.isoformat() for k, v in self._last_run.items()},
        }


# Global scheduler instance (can be started by server startup)
_scheduler: ConfidenceDecayScheduler | None = None


def get_decay_scheduler() -> ConfidenceDecayScheduler | None:
    """Get the global confidence decay scheduler instance."""
    return _scheduler


def set_decay_scheduler(scheduler: ConfidenceDecayScheduler) -> None:
    """Set the global confidence decay scheduler instance."""
    global _scheduler
    _scheduler = scheduler


async def start_decay_scheduler(
    knowledge_mound: KnowledgeMound,
    decay_interval_hours: int = 24,
    workspaces: list[str] | None = None,
) -> ConfidenceDecayScheduler:
    """
    Create and start a global confidence decay scheduler.

    Args:
        knowledge_mound: Knowledge Mound instance
        decay_interval_hours: Interval between cycles
        workspaces: Optional workspaces to monitor

    Returns:
        Started ConfidenceDecayScheduler instance
    """
    global _scheduler

    if _scheduler and _scheduler.is_running:
        logger.warning("Decay scheduler already running, stopping existing one")
        await _scheduler.stop()

    _scheduler = ConfidenceDecayScheduler(
        knowledge_mound=knowledge_mound,
        decay_interval_hours=decay_interval_hours,
        workspaces=workspaces,
    )

    await _scheduler.start()
    return _scheduler


async def stop_decay_scheduler() -> None:
    """Stop the global confidence decay scheduler."""
    global _scheduler
    if _scheduler:
        await _scheduler.stop()
        _scheduler = None
