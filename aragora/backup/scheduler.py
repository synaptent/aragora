"""
Backup Scheduler - Automated backup scheduling and DR drill integration.

Provides automated backup scheduling with:
- Configurable backup intervals (hourly, daily, weekly, monthly)
- Automatic retention policy enforcement
- DR drill integration for backup verification
- Prometheus metrics and alerting
- Event callbacks for notifications

SOC 2 Compliance: CC9.1, CC9.2 (Business Continuity)

Usage:
    from aragora.backup.scheduler import (
        BackupScheduler,
        BackupSchedule,
        get_backup_scheduler,
    )

    # Create scheduler
    scheduler = BackupScheduler(
        backup_manager=manager,
        schedule=BackupSchedule(
            daily=datetime.time(2, 0),  # 2 AM daily
            weekly_day=6,  # Sunday
        ),
    )

    # Start automated backups
    await scheduler.start()

    # Trigger manual backup
    await scheduler.backup_now()
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from enum import Enum
from typing import Any
from collections.abc import Callable
from pathlib import Path

from aragora.backup.manager import get_default_backup_source_path

logger = logging.getLogger(__name__)

# =============================================================================
# Types and Enums
# =============================================================================


class ScheduleType(str, Enum):
    """Types of backup schedules."""

    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"


class SchedulerStatus(str, Enum):
    """Status of the backup scheduler."""

    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class BackupSchedule:
    """Configuration for backup schedule."""

    # Schedule times (None = disabled)
    hourly_minute: int | None = None  # Minute of hour (0-59)
    daily: time | None = None  # Time for daily backup
    weekly_day: int | None = None  # Day of week (0=Monday, 6=Sunday)
    weekly_time: time | None = None  # Time for weekly backup
    monthly_day: int | None = None  # Day of month (1-31)
    monthly_time: time | None = None  # Time for monthly backup

    # Custom cron-like interval (seconds)
    custom_interval_seconds: int | None = None

    # Retry configuration
    max_retries: int = 3
    retry_delay_seconds: int = 60

    # Verification settings
    verify_after_backup: bool = True
    retention_cleanup_after: bool = True

    # DR drill integration
    enable_dr_drills: bool = True
    dr_drill_interval_days: int = 30  # Monthly DR drills

    # Offsite backup integration
    enable_offsite: bool = False
    offsite_after_backup: bool = True  # Upload to offsite after each local backup

    def get_next_backup_time(
        self,
        schedule_type: ScheduleType,
        now: datetime | None = None,
    ) -> datetime | None:
        """Calculate next backup time for the given schedule type."""
        if now is None:
            now = datetime.now(timezone.utc)

        if schedule_type == ScheduleType.HOURLY and self.hourly_minute is not None:
            next_time = now.replace(minute=self.hourly_minute, second=0, microsecond=0)
            if next_time <= now:
                next_time += timedelta(hours=1)
            return next_time

        elif schedule_type == ScheduleType.DAILY and self.daily is not None:
            next_time = now.replace(
                hour=self.daily.hour,
                minute=self.daily.minute,
                second=0,
                microsecond=0,
            )
            if next_time <= now:
                next_time += timedelta(days=1)
            return next_time

        elif schedule_type == ScheduleType.WEEKLY:
            if self.weekly_day is not None and self.weekly_time is not None:
                days_ahead = self.weekly_day - now.weekday()
                if days_ahead < 0:
                    days_ahead += 7
                next_time = now.replace(
                    hour=self.weekly_time.hour,
                    minute=self.weekly_time.minute,
                    second=0,
                    microsecond=0,
                ) + timedelta(days=days_ahead)
                if next_time <= now:
                    next_time += timedelta(days=7)
                return next_time

        elif schedule_type == ScheduleType.MONTHLY:
            if self.monthly_day is not None and self.monthly_time is not None:
                # Try this month first
                try:
                    next_time = now.replace(
                        day=self.monthly_day,
                        hour=self.monthly_time.hour,
                        minute=self.monthly_time.minute,
                        second=0,
                        microsecond=0,
                    )
                    if next_time <= now:
                        # Move to next month
                        if now.month == 12:
                            next_time = next_time.replace(year=now.year + 1, month=1)
                        else:
                            next_time = next_time.replace(month=now.month + 1)
                    return next_time
                except ValueError:
                    logger.debug(
                        "Monthly day %d does not exist in current month, skipping",
                        self.monthly_day,
                    )

        elif schedule_type == ScheduleType.CUSTOM and self.custom_interval_seconds:
            return now + timedelta(seconds=self.custom_interval_seconds)

        return None


@dataclass
class BackupJob:
    """Record of a scheduled or executed backup job."""

    id: str
    schedule_type: ScheduleType
    scheduled_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    status: str = "scheduled"
    backup_id: str | None = None
    verified: bool = False
    error: str | None = None
    retries: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "schedule_type": self.schedule_type.value,
            "scheduled_at": self.scheduled_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status,
            "backup_id": self.backup_id,
            "verified": self.verified,
            "error": self.error,
            "retries": self.retries,
            "metadata": self.metadata,
        }


@dataclass
class SchedulerStats:
    """Statistics for the backup scheduler."""

    status: SchedulerStatus
    total_backups: int = 0
    successful_backups: int = 0
    failed_backups: int = 0
    last_backup_at: datetime | None = None
    last_backup_status: str | None = None
    next_daily: datetime | None = None
    next_weekly: datetime | None = None
    next_monthly: datetime | None = None
    dr_drills_completed: int = 0
    last_dr_drill_at: datetime | None = None
    uptime_seconds: float = 0.0


# Type alias for event callback
EventCallback = Callable[[str, dict[str, Any]], None]


class BackupScheduler:
    """
    Automated backup scheduler with DR drill integration.

    Manages scheduled backups and integrates with the DR drill system
    for automated backup verification and restoration testing.
    """

    def __init__(
        self,
        backup_manager: Any,
        schedule: BackupSchedule | None = None,
        event_callback: EventCallback | None = None,
        storage_path: Path | None = None,
        offsite_manager: Any | None = None,
    ):
        """
        Initialize the backup scheduler.

        Args:
            backup_manager: The BackupManager instance to use
            schedule: Backup schedule configuration
            event_callback: Optional callback for events
            storage_path: Path to store scheduler state
            offsite_manager: Optional OffsiteBackupManager for cloud uploads
        """
        self._manager = backup_manager
        self._schedule = schedule or BackupSchedule(
            daily=time(2, 0),  # 2 AM daily backup by default
        )
        self._event_callback = event_callback
        self._storage_path = storage_path
        self._offsite_manager = offsite_manager

        self._status = SchedulerStatus.STOPPED
        self._started_at: datetime | None = None
        self._tasks: list[asyncio.Task] = []
        self._job_history: list[BackupJob] = []
        self._stats = SchedulerStats(status=SchedulerStatus.STOPPED)
        self._lock = asyncio.Lock()

    @property
    def status(self) -> SchedulerStatus:
        """Get current scheduler status."""
        return self._status

    @property
    def schedule(self) -> BackupSchedule:
        """Get current schedule configuration."""
        return self._schedule

    def set_event_callback(self, callback: EventCallback) -> None:
        """Set the event callback for notifications."""
        self._event_callback = callback

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event if callback is configured."""
        if self._event_callback:
            try:
                self._event_callback(event_type, data)
            except (OSError, RuntimeError, ValueError) as e:
                logger.warning("Failed to emit event %s: %s", event_type, e)

    def _record_metric(
        self,
        operation: str,
        success: bool,
        duration_seconds: float,
    ) -> None:
        """Record Prometheus metrics."""
        try:
            # Metric function may not exist in all deployments
            import importlib

            _metrics = importlib.import_module("aragora.observability.metrics")
            _record_fn = getattr(_metrics, "record_backup_operation", None)
            if _record_fn is not None:
                _record_fn(operation, success, duration_seconds)
        except (ImportError, AttributeError):
            logger.debug("Metrics module not available for backup operation recording")
        except (OSError, RuntimeError, ValueError) as e:
            logger.debug("Failed to record metric: %s", e)

    async def start(self) -> None:
        """Start the backup scheduler."""
        if self._status == SchedulerStatus.RUNNING:
            logger.warning("Backup scheduler already running")
            return

        self._status = SchedulerStatus.RUNNING
        self._started_at = datetime.now(timezone.utc)
        self._stats.status = SchedulerStatus.RUNNING

        logger.info("Starting backup scheduler")

        # Start schedule monitoring tasks
        self._tasks = [
            asyncio.create_task(self._run_daily_schedule()),
            asyncio.create_task(self._run_weekly_schedule()),
            asyncio.create_task(self._run_monthly_schedule()),
        ]

        if self._schedule.hourly_minute is not None:
            self._tasks.append(asyncio.create_task(self._run_hourly_schedule()))

        if self._schedule.custom_interval_seconds:
            self._tasks.append(asyncio.create_task(self._run_custom_schedule()))

        if self._schedule.enable_dr_drills:
            self._tasks.append(asyncio.create_task(self._run_dr_drill_schedule()))

        self._emit_event(
            "backup_scheduler_started",
            {
                "schedule": {
                    "daily": str(self._schedule.daily) if self._schedule.daily else None,
                    "weekly_day": self._schedule.weekly_day,
                    "monthly_day": self._schedule.monthly_day,
                },
            },
        )

    async def stop(self) -> None:
        """Stop the backup scheduler."""
        if self._status == SchedulerStatus.STOPPED:
            return

        logger.info("Stopping backup scheduler")
        self._status = SchedulerStatus.STOPPED
        self._stats.status = SchedulerStatus.STOPPED

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass  # Expected during shutdown — task was intentionally cancelled

        self._tasks.clear()

        self._emit_event("backup_scheduler_stopped", {})

    async def pause(self) -> None:
        """Pause the backup scheduler."""
        self._status = SchedulerStatus.PAUSED
        self._stats.status = SchedulerStatus.PAUSED
        logger.info("Backup scheduler paused")
        self._emit_event("backup_scheduler_paused", {})

    async def resume(self) -> None:
        """Resume the backup scheduler."""
        if self._status == SchedulerStatus.PAUSED:
            self._status = SchedulerStatus.RUNNING
            self._stats.status = SchedulerStatus.RUNNING
            logger.info("Backup scheduler resumed")
            self._emit_event("backup_scheduler_resumed", {})

    async def backup_now(
        self,
        verify: bool = True,
        cleanup: bool = True,
    ) -> BackupJob:
        """
        Trigger an immediate backup.

        Args:
            verify: Whether to verify the backup after creation
            cleanup: Whether to run retention cleanup after backup

        Returns:
            BackupJob with the result
        """
        import uuid

        job = BackupJob(
            id=str(uuid.uuid4()),
            schedule_type=ScheduleType.CUSTOM,
            scheduled_at=datetime.now(timezone.utc),
        )

        await self._execute_backup(job, verify=verify, cleanup=cleanup)
        return job

    async def _execute_backup(
        self,
        job: BackupJob,
        verify: bool = True,
        cleanup: bool = True,
    ) -> None:
        """Execute a backup job."""
        import time as time_module

        async with self._lock:
            job.started_at = datetime.now(timezone.utc)
            job.status = "running"

            start_time = time_module.time()
            success = False

            try:
                # Create backup
                logger.info("Starting backup job %s (type=%s)", job.id, job.schedule_type.value)

                backup_metadata = self._manager.create_backup(get_default_backup_source_path())
                job.backup_id = backup_metadata.id

                # Verify if requested
                if verify and self._schedule.verify_after_backup:
                    logger.info("Verifying backup %s", backup_metadata.id)
                    result = self._manager.verify_backup(backup_metadata.id)
                    job.verified = result.verified
                    if not result.verified:
                        logger.warning("Backup verification failed: %s", result.errors)
                        job.metadata["verification_errors"] = result.errors

                # Upload to offsite storage if configured
                if (
                    self._offsite_manager is not None
                    and self._schedule.enable_offsite
                    and self._schedule.offsite_after_backup
                ):
                    try:
                        backup_path = backup_metadata.backup_path
                        offsite_record = self._offsite_manager.upload_backup(
                            backup_path,
                            {"source_backup_id": backup_metadata.id},
                        )
                        job.metadata["offsite_id"] = offsite_record.id
                        logger.info("Offsite upload completed: %s", offsite_record.id)
                    except (OSError, RuntimeError) as e:
                        logger.error("Offsite upload failed: %s", e)
                        job.metadata["offsite_error"] = str(e)

                # Cleanup expired backups
                if cleanup and self._schedule.retention_cleanup_after:
                    logger.info("Running retention cleanup")
                    removed = self._manager.cleanup_expired()
                    job.metadata["removed_backups"] = removed

                job.status = "completed"
                job.completed_at = datetime.now(timezone.utc)
                success = True

                self._stats.total_backups += 1
                self._stats.successful_backups += 1
                self._stats.last_backup_at = job.completed_at
                self._stats.last_backup_status = "success"

                self._emit_event(
                    "backup_completed",
                    {
                        "job_id": job.id,
                        "backup_id": backup_metadata.id,
                        "verified": job.verified,
                        "duration_seconds": time_module.time() - start_time,
                    },
                )

            except (OSError, IOError, RuntimeError) as e:
                job.status = "failed"
                job.error = str(e)
                job.completed_at = datetime.now(timezone.utc)

                self._stats.total_backups += 1
                self._stats.failed_backups += 1
                self._stats.last_backup_at = job.completed_at
                self._stats.last_backup_status = "failed"

                logger.error("Backup job %s failed: %s", job.id, e)

                self._emit_event(
                    "backup_failed",
                    {
                        "job_id": job.id,
                        "error": str(e),
                        "retries": job.retries,
                    },
                )

                # Retry if configured
                if job.retries < self._schedule.max_retries:
                    job.retries += 1
                    logger.info("Retrying backup job %s (attempt %s)", job.id, job.retries)
                    await asyncio.sleep(self._schedule.retry_delay_seconds)
                    await self._execute_backup(job, verify=verify, cleanup=cleanup)

            finally:
                duration = time_module.time() - start_time
                self._record_metric("scheduled_backup", success, duration)
                self._job_history.append(job)

    async def _run_hourly_schedule(self) -> None:
        """Run hourly backup schedule."""
        while self._status == SchedulerStatus.RUNNING:
            try:
                next_time = self._schedule.get_next_backup_time(ScheduleType.HOURLY)
                if next_time:
                    wait_seconds = (next_time - datetime.now(timezone.utc)).total_seconds()
                    if wait_seconds > 0:
                        await asyncio.sleep(wait_seconds)

                    if self._status == SchedulerStatus.RUNNING:
                        job = BackupJob(
                            id=(
                                str(uuid.uuid4())
                                if "uuid" in dir()
                                else f"hourly-{datetime.now().timestamp()}"
                            ),
                            schedule_type=ScheduleType.HOURLY,
                            scheduled_at=next_time,
                        )
                        await self._execute_backup(job)
                else:
                    await asyncio.sleep(60)  # Check again in a minute
            except asyncio.CancelledError:
                break
            except (OSError, IOError, RuntimeError) as e:
                logger.error("Hourly schedule error: %s", e)
                await asyncio.sleep(60)

    async def _run_daily_schedule(self) -> None:
        """Run daily backup schedule."""
        import uuid

        while self._status == SchedulerStatus.RUNNING:
            try:
                next_time = self._schedule.get_next_backup_time(ScheduleType.DAILY)
                self._stats.next_daily = next_time

                if next_time:
                    wait_seconds = (next_time - datetime.now(timezone.utc)).total_seconds()
                    if wait_seconds > 0:
                        logger.info("Next daily backup at %s (%.0fs)", next_time, wait_seconds)
                        await asyncio.sleep(wait_seconds)

                    if self._status == SchedulerStatus.RUNNING:
                        job = BackupJob(
                            id=str(uuid.uuid4()),
                            schedule_type=ScheduleType.DAILY,
                            scheduled_at=next_time,
                        )
                        await self._execute_backup(job)
                else:
                    await asyncio.sleep(3600)  # Check again in an hour
            except asyncio.CancelledError:
                break
            except (OSError, IOError, RuntimeError) as e:
                logger.error("Daily schedule error: %s", e)
                await asyncio.sleep(300)

    async def _run_weekly_schedule(self) -> None:
        """Run weekly backup schedule."""
        import uuid

        while self._status == SchedulerStatus.RUNNING:
            try:
                next_time = self._schedule.get_next_backup_time(ScheduleType.WEEKLY)
                self._stats.next_weekly = next_time

                if next_time:
                    wait_seconds = (next_time - datetime.now(timezone.utc)).total_seconds()
                    if wait_seconds > 0:
                        logger.info("Next weekly backup at %s", next_time)
                        await asyncio.sleep(wait_seconds)

                    if self._status == SchedulerStatus.RUNNING:
                        job = BackupJob(
                            id=str(uuid.uuid4()),
                            schedule_type=ScheduleType.WEEKLY,
                            scheduled_at=next_time,
                        )
                        await self._execute_backup(job)
                else:
                    await asyncio.sleep(3600)
            except asyncio.CancelledError:
                break
            except (OSError, IOError, RuntimeError) as e:
                logger.error("Weekly schedule error: %s", e)
                await asyncio.sleep(300)

    async def _run_monthly_schedule(self) -> None:
        """Run monthly backup schedule."""
        import uuid

        while self._status == SchedulerStatus.RUNNING:
            try:
                next_time = self._schedule.get_next_backup_time(ScheduleType.MONTHLY)
                self._stats.next_monthly = next_time

                if next_time:
                    wait_seconds = (next_time - datetime.now(timezone.utc)).total_seconds()
                    if wait_seconds > 0:
                        logger.info("Next monthly backup at %s", next_time)
                        await asyncio.sleep(wait_seconds)

                    if self._status == SchedulerStatus.RUNNING:
                        job = BackupJob(
                            id=str(uuid.uuid4()),
                            schedule_type=ScheduleType.MONTHLY,
                            scheduled_at=next_time,
                        )
                        await self._execute_backup(job)
                else:
                    await asyncio.sleep(3600)
            except asyncio.CancelledError:
                break
            except (OSError, IOError, RuntimeError) as e:
                logger.error("Monthly schedule error: %s", e)
                await asyncio.sleep(300)

    async def _run_custom_schedule(self) -> None:
        """Run custom interval backup schedule."""
        import uuid

        while self._status == SchedulerStatus.RUNNING:
            try:
                if self._schedule.custom_interval_seconds:
                    await asyncio.sleep(self._schedule.custom_interval_seconds)

                    if self._status == SchedulerStatus.RUNNING:
                        job = BackupJob(
                            id=str(uuid.uuid4()),
                            schedule_type=ScheduleType.CUSTOM,
                            scheduled_at=datetime.now(timezone.utc),
                        )
                        await self._execute_backup(job)
                else:
                    break
            except asyncio.CancelledError:
                break
            except (OSError, IOError, RuntimeError) as e:
                logger.error("Custom schedule error: %s", e)
                await asyncio.sleep(60)

    async def _run_dr_drill_schedule(self) -> None:
        """Run DR drill schedule for backup verification."""

        interval_seconds = self._schedule.dr_drill_interval_days * 24 * 3600

        while self._status == SchedulerStatus.RUNNING:
            try:
                await asyncio.sleep(interval_seconds)

                if self._status == SchedulerStatus.RUNNING:
                    await self._execute_dr_drill()

            except asyncio.CancelledError:
                break
            except (OSError, IOError, RuntimeError) as e:
                logger.error("DR drill schedule error: %s", e)
                await asyncio.sleep(3600)

    async def _execute_dr_drill(self) -> dict[str, Any]:
        """Execute a DR drill for backup verification.

        Uses the BackupManager's ``restore_drill()`` method when available
        (produces a full ``RestoreDrillReport`` with compliance evidence).
        Falls back to the legacy dry-run approach if the method is missing.
        """
        import time as time_module

        logger.info("Starting DR drill: backup restoration test")
        start_time = time_module.time()

        result: dict[str, Any] = {
            "drill_type": "backup_restoration",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "steps": [],
            "success": False,
            "rto_seconds": 0.0,
            "rpo_seconds": 0.0,
        }

        try:
            # Use restore_drill() if available (BackupManager enhancement)
            restore_drill_fn = getattr(self._manager, "restore_drill", None)
            if callable(restore_drill_fn):
                drill_report = restore_drill_fn()
                rto_seconds = time_module.time() - start_time

                result["drill_id"] = drill_report.drill_id
                result["backup_id"] = drill_report.backup_id
                result["success"] = drill_report.status == "passed"
                result["rto_seconds"] = rto_seconds
                result["steps"].append(
                    {
                        "step": "restore_drill",
                        "status": drill_report.status,
                        "tables_verified": drill_report.tables_verified,
                        "rows_verified": drill_report.rows_verified,
                        "checksum_valid": drill_report.checksum_valid,
                        "schema_valid": drill_report.schema_valid,
                        "integrity_valid": drill_report.integrity_valid,
                        "errors": drill_report.errors,
                    }
                )

                if result["success"]:
                    self._stats.dr_drills_completed += 1
                    self._stats.last_dr_drill_at = datetime.now(timezone.utc)

                    self._emit_event(
                        "dr_drill_completed",
                        {
                            "drill_type": "backup_restoration",
                            "success": True,
                            "drill_id": drill_report.drill_id,
                            "rto_seconds": rto_seconds,
                        },
                    )
                else:
                    self._emit_event(
                        "dr_drill_failed",
                        {
                            "drill_type": "backup_restoration",
                            "drill_id": drill_report.drill_id,
                            "errors": drill_report.errors,
                        },
                    )

                result["completed_at"] = datetime.now(timezone.utc).isoformat()
                return result

            # Fallback: legacy dry-run approach
            backups = self._manager.list_backups()
            if not backups:
                result["error"] = "No backups available for DR drill"
                return result

            latest_backup = backups[0]
            result["backup_id"] = latest_backup.id

            # Calculate RPO
            rpo_seconds = (datetime.now(timezone.utc) - latest_backup.created_at).total_seconds()
            result["rpo_seconds"] = rpo_seconds
            result["steps"].append(
                {
                    "step": "calculate_rpo",
                    "rpo_seconds": rpo_seconds,
                    "status": "completed",
                }
            )

            # Verify backup integrity
            verify_result = self._manager.verify_backup(latest_backup.id)
            result["steps"].append(
                {
                    "step": "verify_integrity",
                    "verified": verify_result.verified,
                    "checksum_valid": verify_result.checksum_valid,
                    "status": "completed" if verify_result.verified else "failed",
                }
            )

            if not verify_result.verified:
                result["error"] = f"Backup verification failed: {verify_result.errors}"
                return result

            # Test restore (dry run)
            with tempfile.TemporaryDirectory(prefix="dr_drill_") as temp_dir:
                temp_restore_path = Path(temp_dir) / "test_restore.db"
                restore_success = self._manager.restore_backup(
                    latest_backup.id,
                    target_path=temp_restore_path,
                    dry_run=True,
                )
            result["steps"].append(
                {
                    "step": "test_restore",
                    "dry_run": True,
                    "success": restore_success,
                    "status": "completed" if restore_success else "failed",
                }
            )

            # Calculate RTO
            rto_seconds = time_module.time() - start_time
            result["rto_seconds"] = rto_seconds
            result["steps"].append(
                {
                    "step": "calculate_rto",
                    "rto_seconds": rto_seconds,
                    "status": "completed",
                }
            )

            result["success"] = True
            result["completed_at"] = datetime.now(timezone.utc).isoformat()

            self._stats.dr_drills_completed += 1
            self._stats.last_dr_drill_at = datetime.now(timezone.utc)

            self._emit_event(
                "dr_drill_completed",
                {
                    "drill_type": "backup_restoration",
                    "success": True,
                    "rto_seconds": rto_seconds,
                    "rpo_seconds": rpo_seconds,
                },
            )

        except (OSError, IOError, RuntimeError) as e:
            logger.error("DR drill failed: %s", e)
            result["error"] = str(e)
            result["success"] = False

            self._emit_event(
                "dr_drill_failed",
                {
                    "drill_type": "backup_restoration",
                    "error": str(e),
                },
            )

        return result

    def get_stats(self) -> SchedulerStats:
        """Get scheduler statistics."""
        if self._started_at:
            self._stats.uptime_seconds = (
                datetime.now(timezone.utc) - self._started_at
            ).total_seconds()
        return self._stats

    def get_job_history(self, limit: int = 100) -> list[BackupJob]:
        """Get recent backup job history."""
        return self._job_history[-limit:]


# =============================================================================
# Global Instance
# =============================================================================

_backup_scheduler: BackupScheduler | None = None


def get_backup_scheduler() -> BackupScheduler | None:
    """Get the global backup scheduler instance."""
    return _backup_scheduler


def set_backup_scheduler(scheduler: BackupScheduler | None) -> None:
    """Set the global backup scheduler instance."""
    global _backup_scheduler
    _backup_scheduler = scheduler


async def start_backup_scheduler(
    backup_manager: Any,
    schedule: BackupSchedule | None = None,
) -> BackupScheduler:
    """
    Start the global backup scheduler.

    Args:
        backup_manager: The BackupManager to use
        schedule: Optional schedule configuration

    Returns:
        The started BackupScheduler instance
    """
    global _backup_scheduler

    if _backup_scheduler is not None:
        await _backup_scheduler.stop()

    _backup_scheduler = BackupScheduler(
        backup_manager=backup_manager,
        schedule=schedule,
    )
    await _backup_scheduler.start()

    return _backup_scheduler


async def stop_backup_scheduler() -> None:
    """Stop the global backup scheduler."""
    global _backup_scheduler

    if _backup_scheduler is not None:
        await _backup_scheduler.stop()
        _backup_scheduler = None


# Import uuid at module level for use in methods
import uuid

__all__ = [
    "BackupScheduler",
    "BackupSchedule",
    "BackupJob",
    "ScheduleType",
    "SchedulerStatus",
    "SchedulerStats",
    "get_backup_scheduler",
    "set_backup_scheduler",
    "start_backup_scheduler",
    "stop_backup_scheduler",
]
