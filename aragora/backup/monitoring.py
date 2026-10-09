"""
Backup Monitoring with Prometheus Metrics.

Provides monitoring for backup operations:
- Backup age (time since last backup)
- Backup size
- Restore time measurements
- RPO/RTO compliance status
- Recovery progress monitoring

Usage:
    from aragora.backup.monitoring import (
        record_backup_created,
        record_backup_restored,
        get_backup_age_seconds,
    )

    # Record a backup operation
    record_backup_created(size_bytes=1024*1024, duration_seconds=60)

    # Check backup freshness
    age = get_backup_age_seconds()
    if age > 3600:  # More than 1 hour
        alert("Backup is stale!")

Requirements:
    pip install prometheus-client

SLA Targets (from docs/SLA.md):
    Free:       RTO=24h, RPO=24h
    Pro:        RTO=4h,  RPO=1h
    Enterprise: RTO=1h,  RPO=15m
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Prometheus metrics - initialized lazily
_initialized = False

# Metric instances (will be set during initialization)
BACKUP_CREATED_TOTAL: Any = None
BACKUP_SIZE_BYTES: Any = None
BACKUP_DURATION_SECONDS: Any = None
BACKUP_LAST_TIMESTAMP: Any = None
BACKUP_AGE_SECONDS: Any = None
BACKUP_VERIFICATION_TOTAL: Any = None
BACKUP_VERIFICATION_FAILURES: Any = None
RESTORE_DURATION_SECONDS: Any = None
RESTORE_TOTAL: Any = None
RESTORE_FAILURES: Any = None
RPO_COMPLIANCE: Any = None
RTO_COMPLIANCE: Any = None

# SLA targets in seconds
SLA_TARGETS = {
    "free": {"rto": 24 * 3600, "rpo": 24 * 3600},
    "pro": {"rto": 4 * 3600, "rpo": 1 * 3600},
    "enterprise": {"rto": 1 * 3600, "rpo": 15 * 60},
}


def _metric_with_single_label(metric: Any, preferred_label: str, value: str) -> Any:
    """Return a labeled metric, tolerating reused collectors with different label names."""
    labelnames = tuple(getattr(metric, "_labelnames", ()) or ())
    if not labelnames:
        return metric
    label = preferred_label if preferred_label in labelnames else labelnames[0]
    return metric.labels(**{label: value})


def _init_metrics() -> None:
    """Initialize Prometheus metrics lazily."""
    global _initialized
    global BACKUP_CREATED_TOTAL, BACKUP_SIZE_BYTES, BACKUP_DURATION_SECONDS
    global BACKUP_LAST_TIMESTAMP, BACKUP_AGE_SECONDS
    global BACKUP_VERIFICATION_TOTAL, BACKUP_VERIFICATION_FAILURES
    global RESTORE_DURATION_SECONDS, RESTORE_TOTAL, RESTORE_FAILURES
    global RPO_COMPLIANCE, RTO_COMPLIANCE

    if _initialized:
        return

    try:
        from aragora.observability.metrics.base import (
            get_or_create_counter,
            get_or_create_gauge,
            get_or_create_histogram,
        )

        # Backup creation metrics
        BACKUP_CREATED_TOTAL = get_or_create_counter(
            "aragora_backup_created_total",
            "Total number of backups created",
            ["backup_type"],
        )

        BACKUP_SIZE_BYTES = get_or_create_gauge(
            "aragora_backup_size_bytes",
            "Size of the latest backup in bytes",
            ["backup_type"],
        )

        BACKUP_DURATION_SECONDS = get_or_create_histogram(
            "aragora_backup_duration_seconds",
            "Time taken to create a backup",
            ["backup_type"],
            buckets=[1, 5, 10, 30, 60, 120, 300, 600],
        )

        BACKUP_LAST_TIMESTAMP = get_or_create_gauge(
            "aragora_backup_last_timestamp",
            "Unix timestamp of the last successful backup",
        )

        BACKUP_AGE_SECONDS = get_or_create_gauge(
            "aragora_backup_age_seconds",
            "Age of the latest backup in seconds",
        )

        # Verification metrics
        BACKUP_VERIFICATION_TOTAL = get_or_create_counter(
            "aragora_backup_verification_total",
            "Total backup verifications performed",
            ["result"],
        )

        BACKUP_VERIFICATION_FAILURES = get_or_create_counter(
            "aragora_backup_verification_failures_total",
            "Total backup verification failures",
            ["failure_type"],
        )

        # Restore metrics
        RESTORE_DURATION_SECONDS = get_or_create_histogram(
            "aragora_restore_duration_seconds",
            "Time taken to restore from backup",
            buckets=[1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600],
        )

        RESTORE_TOTAL = get_or_create_counter(
            "aragora_restore_total",
            "Total restore operations",
            ["result"],
        )

        RESTORE_FAILURES = get_or_create_counter(
            "aragora_restore_failures_total",
            "Total restore failures",
            ["failure_type"],
        )

        # SLA compliance gauges (1 = compliant, 0 = non-compliant)
        RPO_COMPLIANCE = get_or_create_gauge(
            "aragora_rpo_compliance",
            "RPO compliance status (1=compliant, 0=non-compliant)",
            ["tier"],
        )

        RTO_COMPLIANCE = get_or_create_gauge(
            "aragora_rto_compliance",
            "RTO compliance status (1=compliant, 0=non-compliant)",
            ["tier"],
        )

        _initialized = True
        logger.info("Backup monitoring metrics initialized")

    except ImportError:
        logger.warning(
            "prometheus_client not installed, backup metrics disabled. "
            "Install with: pip install prometheus-client"
        )


@dataclass
class BackupMetrics:
    """Current backup metrics snapshot."""

    last_backup_timestamp: float | None = None
    backup_age_seconds: float | None = None
    last_backup_size_bytes: int | None = None
    last_restore_duration: float | None = None
    rpo_compliant: dict[str, bool] = field(default_factory=dict)
    rto_compliant: dict[str, bool] = field(default_factory=dict)


# In-memory state for metrics (used when prometheus_client not available)
_last_backup_timestamp: float | None = None
_last_backup_size: int | None = None
_last_restore_duration: float | None = None


def record_backup_created(
    size_bytes: int,
    duration_seconds: float,
    backup_type: str = "full",
) -> None:
    """Record a successful backup creation.

    Args:
        size_bytes: Size of the backup in bytes
        duration_seconds: Time taken to create the backup
        backup_type: Type of backup (full, incremental, differential)
    """
    global _last_backup_timestamp, _last_backup_size

    _init_metrics()
    _last_backup_timestamp = time.time()
    _last_backup_size = size_bytes

    if BACKUP_CREATED_TOTAL is not None:
        BACKUP_CREATED_TOTAL.labels(backup_type=backup_type).inc()

    if BACKUP_SIZE_BYTES is not None:
        _metric_with_single_label(BACKUP_SIZE_BYTES, "backup_type", backup_type).set(size_bytes)

    if BACKUP_DURATION_SECONDS is not None:
        _metric_with_single_label(BACKUP_DURATION_SECONDS, "backup_type", backup_type).observe(
            duration_seconds
        )

    if BACKUP_LAST_TIMESTAMP is not None:
        BACKUP_LAST_TIMESTAMP.set(_last_backup_timestamp)

    if BACKUP_AGE_SECONDS is not None:
        BACKUP_AGE_SECONDS.set(0)  # Just created

    # Update compliance status
    _update_compliance_status()

    logger.info(
        "Backup created: type=%s, size=%s, duration=%.2fs",
        backup_type,
        size_bytes,
        duration_seconds,
    )


def record_backup_verified(success: bool, failure_type: str | None = None) -> None:
    """Record a backup verification result.

    Args:
        success: Whether verification succeeded
        failure_type: Type of failure if not successful
    """
    _init_metrics()

    if BACKUP_VERIFICATION_TOTAL is not None:
        result = "success" if success else "failure"
        BACKUP_VERIFICATION_TOTAL.labels(result=result).inc()

    if not success and failure_type and BACKUP_VERIFICATION_FAILURES is not None:
        BACKUP_VERIFICATION_FAILURES.labels(failure_type=failure_type).inc()


def record_restore_completed(
    duration_seconds: float,
    success: bool,
    failure_type: str | None = None,
) -> None:
    """Record a restore operation result.

    Args:
        duration_seconds: Time taken for restore
        success: Whether restore succeeded
        failure_type: Type of failure if not successful
    """
    global _last_restore_duration

    _init_metrics()
    _last_restore_duration = duration_seconds

    if RESTORE_DURATION_SECONDS is not None:
        RESTORE_DURATION_SECONDS.observe(duration_seconds)

    if RESTORE_TOTAL is not None:
        result = "success" if success else "failure"
        RESTORE_TOTAL.labels(result=result).inc()

    if not success and failure_type and RESTORE_FAILURES is not None:
        RESTORE_FAILURES.labels(failure_type=failure_type).inc()

    # Update RTO compliance
    _update_compliance_status()

    logger.info("Restore completed: success=%s, duration=%.2fs", success, duration_seconds)


def update_backup_age() -> float | None:
    """Update and return the current backup age in seconds.

    Returns:
        Backup age in seconds, or None if no backup exists
    """
    _init_metrics()

    if _last_backup_timestamp is None:
        return None

    age = time.time() - _last_backup_timestamp

    if BACKUP_AGE_SECONDS is not None:
        BACKUP_AGE_SECONDS.set(age)

    _update_compliance_status()

    return age


def get_backup_age_seconds() -> float | None:
    """Get the current backup age in seconds.

    Returns:
        Backup age in seconds, or None if no backup exists
    """
    if _last_backup_timestamp is None:
        return None
    return time.time() - _last_backup_timestamp


def get_current_metrics() -> BackupMetrics:
    """Get current backup metrics snapshot.

    Returns:
        BackupMetrics with current state
    """
    backup_age = get_backup_age_seconds()

    rpo_compliant = {}
    rto_compliant = {}

    for tier, targets in SLA_TARGETS.items():
        if backup_age is not None:
            rpo_compliant[tier] = backup_age <= targets["rpo"]
        else:
            rpo_compliant[tier] = False

        if _last_restore_duration is not None:
            rto_compliant[tier] = _last_restore_duration <= targets["rto"]
        else:
            rto_compliant[tier] = True  # Assume compliant if not tested

    return BackupMetrics(
        last_backup_timestamp=_last_backup_timestamp,
        backup_age_seconds=backup_age,
        last_backup_size_bytes=_last_backup_size,
        last_restore_duration=_last_restore_duration,
        rpo_compliant=rpo_compliant,
        rto_compliant=rto_compliant,
    )


def _update_compliance_status() -> None:
    """Update RPO and RTO compliance gauges."""
    if RPO_COMPLIANCE is None or RTO_COMPLIANCE is None:
        return

    backup_age = get_backup_age_seconds()

    for tier, targets in SLA_TARGETS.items():
        # RPO compliance
        if backup_age is not None:
            rpo_ok = 1 if backup_age <= targets["rpo"] else 0
        else:
            rpo_ok = 0  # No backup = non-compliant
        RPO_COMPLIANCE.labels(tier=tier).set(rpo_ok)

        # RTO compliance
        if _last_restore_duration is not None:
            rto_ok = 1 if _last_restore_duration <= targets["rto"] else 0
        else:
            rto_ok = 1  # Not tested = assume compliant
        RTO_COMPLIANCE.labels(tier=tier).set(rto_ok)


def check_rpo_breach(tier: str = "pro") -> bool:
    """Check if RPO is breached for a given tier.

    Args:
        tier: SLA tier to check (free, pro, enterprise)

    Returns:
        True if RPO is breached (backup too old)
    """
    if tier not in SLA_TARGETS:
        raise ValueError(f"Unknown tier: {tier}")

    backup_age = get_backup_age_seconds()
    if backup_age is None:
        return True  # No backup = breached

    return backup_age > SLA_TARGETS[tier]["rpo"]


def check_rto_breach(tier: str = "pro") -> bool:
    """Check if RTO is breached for a given tier.

    Args:
        tier: SLA tier to check (free, pro, enterprise)

    Returns:
        True if last restore exceeded RTO
    """
    if tier not in SLA_TARGETS:
        raise ValueError(f"Unknown tier: {tier}")

    if _last_restore_duration is None:
        return False  # No restore = not breached

    return _last_restore_duration > SLA_TARGETS[tier]["rto"]


# Alerting helpers
def get_alerts() -> list[dict]:
    """Get list of current backup-related alerts.

    Returns:
        List of alert dictionaries with severity and message
    """
    alerts = []

    backup_age = get_backup_age_seconds()

    if backup_age is None:
        alerts.append(
            {
                "severity": "critical",
                "message": "No backups found",
                "metric": "backup_age",
            }
        )
    else:
        # Check against each tier
        for tier, targets in SLA_TARGETS.items():
            if backup_age > targets["rpo"]:
                severity = "critical" if tier == "enterprise" else "warning"
                alerts.append(
                    {
                        "severity": severity,
                        "message": f"Backup age ({backup_age / 3600:.1f}h) exceeds {tier} RPO ({targets['rpo'] / 3600:.1f}h)",
                        "metric": "backup_age",
                        "tier": tier,
                    }
                )
                break  # Only report most severe breach

    return alerts


# =============================================================================
# Recovery Progress Monitoring
# =============================================================================


class RecoveryPhase(str, Enum):
    """Phases of recovery operation."""

    INITIALIZING = "initializing"
    DOWNLOADING = "downloading"
    DECOMPRESSING = "decompressing"
    VERIFYING = "verifying"
    RESTORING = "restoring"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class RecoveryProgress:
    """Progress of a recovery operation."""

    recovery_id: str
    backup_id: str
    phase: RecoveryPhase
    percent_complete: float = 0.0
    bytes_processed: int = 0
    total_bytes: int = 0
    objects_processed: int = 0
    total_objects: int = 0
    started_at: datetime | None = None
    estimated_completion: datetime | None = None
    rate_bytes_per_sec: float = 0.0
    rate_objects_per_sec: float = 0.0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def time_remaining_seconds(self) -> float | None:
        """Calculate estimated time remaining in seconds."""
        if self.rate_bytes_per_sec <= 0 or self.total_bytes <= 0:
            return None
        remaining_bytes = self.total_bytes - self.bytes_processed
        if self.rate_bytes_per_sec > 0:
            return remaining_bytes / self.rate_bytes_per_sec
        return None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "recovery_id": self.recovery_id,
            "backup_id": self.backup_id,
            "phase": self.phase.value,
            "percent_complete": self.percent_complete,
            "bytes_processed": self.bytes_processed,
            "total_bytes": self.total_bytes,
            "objects_processed": self.objects_processed,
            "total_objects": self.total_objects,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "estimated_completion": (
                self.estimated_completion.isoformat() if self.estimated_completion else None
            ),
            "rate_bytes_per_sec": self.rate_bytes_per_sec,
            "rate_objects_per_sec": self.rate_objects_per_sec,
            "time_remaining_seconds": self.time_remaining_seconds(),
            "error": self.error,
            "metadata": self.metadata,
        }


# Recovery Progress Prometheus metrics - initialized lazily
_recovery_metrics_initialized = False

RECOVERY_PROGRESS_PERCENT: Any = None
RECOVERY_BYTES_PROCESSED: Any = None
RECOVERY_OBJECTS_PROCESSED: Any = None
RECOVERY_RATE_BYTES: Any = None
RECOVERY_RATE_OBJECTS: Any = None
RECOVERY_PHASE: Any = None
RECOVERY_OPERATIONS_TOTAL: Any = None
RECOVERY_DURATION_SECONDS: Any = None


def _init_recovery_metrics() -> None:
    """Initialize recovery progress Prometheus metrics lazily."""
    global _recovery_metrics_initialized
    global RECOVERY_PROGRESS_PERCENT, RECOVERY_BYTES_PROCESSED
    global RECOVERY_OBJECTS_PROCESSED, RECOVERY_RATE_BYTES
    global RECOVERY_RATE_OBJECTS, RECOVERY_PHASE
    global RECOVERY_OPERATIONS_TOTAL, RECOVERY_DURATION_SECONDS

    if _recovery_metrics_initialized:
        return

    try:
        from prometheus_client import Counter, Gauge, Histogram

        RECOVERY_PROGRESS_PERCENT = Gauge(
            "aragora_recovery_progress_percent",
            "Recovery operation progress percentage",
            ["recovery_id", "backup_id"],
        )

        RECOVERY_BYTES_PROCESSED = Gauge(
            "aragora_recovery_bytes_processed",
            "Bytes processed in current recovery operation",
            ["recovery_id", "backup_id"],
        )

        RECOVERY_OBJECTS_PROCESSED = Gauge(
            "aragora_recovery_objects_processed",
            "Objects processed in current recovery operation",
            ["recovery_id", "backup_id"],
        )

        RECOVERY_RATE_BYTES = Gauge(
            "aragora_recovery_rate_bytes_per_second",
            "Current recovery rate in bytes per second",
            ["recovery_id", "backup_id"],
        )

        RECOVERY_RATE_OBJECTS = Gauge(
            "aragora_recovery_rate_objects_per_second",
            "Current recovery rate in objects per second",
            ["recovery_id", "backup_id"],
        )

        RECOVERY_PHASE = Gauge(
            "aragora_recovery_phase",
            "Current recovery phase (encoded as ordinal)",
            ["recovery_id", "backup_id", "phase"],
        )

        RECOVERY_OPERATIONS_TOTAL = Counter(
            "aragora_recovery_operations_total",
            "Total recovery operations",
            ["result"],
        )

        RECOVERY_DURATION_SECONDS = Histogram(
            "aragora_recovery_duration_seconds",
            "Recovery operation duration in seconds",
            ["result"],
            buckets=[10, 30, 60, 120, 300, 600, 1200, 1800, 3600, 7200],
        )

        _recovery_metrics_initialized = True
        logger.info("Recovery progress metrics initialized")

    except ImportError:
        logger.warning(
            "prometheus_client not installed, recovery metrics disabled. "
            "Install with: pip install prometheus-client"
        )


# Type alias for progress callback
ProgressCallback = Callable[[RecoveryProgress], None]


class RecoveryProgressMonitor:
    """
    Monitor recovery operation progress.

    Features:
    - Track recovery progress in real-time
    - Estimate time remaining
    - Monitor recovery rate (bytes/sec, objects/sec)
    - Expose Prometheus metrics
    - Health check endpoint support
    """

    def __init__(
        self,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        """
        Initialize the recovery progress monitor.

        Args:
            progress_callback: Optional callback for progress updates
        """
        self._progress_callback = progress_callback
        self._active_recoveries: dict[str, RecoveryProgress] = {}
        self._completed_recoveries: list[RecoveryProgress] = []
        self._max_history_size: int = 100

        # Initialize metrics
        _init_recovery_metrics()

    def set_progress_callback(self, callback: ProgressCallback) -> None:
        """Set the progress callback."""
        self._progress_callback = callback

    def start_recovery(
        self,
        recovery_id: str,
        backup_id: str,
        total_bytes: int = 0,
        total_objects: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> RecoveryProgress:
        """
        Start tracking a recovery operation.

        Args:
            recovery_id: Unique identifier for this recovery
            backup_id: ID of the backup being recovered
            total_bytes: Total bytes to recover (0 if unknown)
            total_objects: Total objects to recover (0 if unknown)
            metadata: Optional metadata

        Returns:
            RecoveryProgress instance
        """
        progress = RecoveryProgress(
            recovery_id=recovery_id,
            backup_id=backup_id,
            phase=RecoveryPhase.INITIALIZING,
            total_bytes=total_bytes,
            total_objects=total_objects,
            started_at=datetime.now(timezone.utc),
            metadata=metadata or {},
        )

        self._active_recoveries[recovery_id] = progress
        self._update_metrics(progress)

        logger.info("Started tracking recovery %s for backup %s", recovery_id, backup_id)

        if self._progress_callback:
            try:
                self._progress_callback(progress)
            except (OSError, RuntimeError, ValueError) as e:
                logger.error("Progress callback failed: %s", e)

        return progress

    def update_progress(
        self,
        recovery_id: str,
        phase: RecoveryPhase | None = None,
        bytes_processed: int | None = None,
        objects_processed: int | None = None,
        total_bytes: int | None = None,
        total_objects: int | None = None,
        error: str | None = None,
    ) -> RecoveryProgress | None:
        """
        Update recovery progress.

        Args:
            recovery_id: ID of the recovery operation
            phase: New phase (optional)
            bytes_processed: Bytes processed so far
            objects_processed: Objects processed so far
            total_bytes: Update total bytes if known
            total_objects: Update total objects if known
            error: Error message if failed

        Returns:
            Updated RecoveryProgress or None if not found
        """
        progress = self._active_recoveries.get(recovery_id)
        if not progress:
            logger.warning("Recovery %s not found", recovery_id)
            return None

        now = time.time()

        # Update phase
        if phase is not None:
            progress.phase = phase

        # Update totals if provided
        if total_bytes is not None:
            progress.total_bytes = total_bytes
        if total_objects is not None:
            progress.total_objects = total_objects

        # Calculate rates based on previous values
        if bytes_processed is not None and progress.started_at:
            elapsed = now - progress.started_at.timestamp()
            if elapsed > 0:
                progress.rate_bytes_per_sec = bytes_processed / elapsed
            progress.bytes_processed = bytes_processed

        if objects_processed is not None and progress.started_at:
            elapsed = now - progress.started_at.timestamp()
            if elapsed > 0:
                progress.rate_objects_per_sec = objects_processed / elapsed
            progress.objects_processed = objects_processed

        # Calculate percent complete
        if progress.total_bytes > 0:
            progress.percent_complete = (progress.bytes_processed / progress.total_bytes) * 100
        elif progress.total_objects > 0:
            progress.percent_complete = (progress.objects_processed / progress.total_objects) * 100

        # Estimate completion time
        time_remaining = progress.time_remaining_seconds()
        if time_remaining is not None and time_remaining > 0:
            progress.estimated_completion = datetime.now(timezone.utc) + timedelta(
                seconds=time_remaining
            )

        # Record error
        if error:
            progress.error = error
            progress.phase = RecoveryPhase.FAILED

        self._update_metrics(progress)

        if self._progress_callback:
            try:
                self._progress_callback(progress)
            except (OSError, RuntimeError, ValueError) as e:
                logger.error("Progress callback failed: %s", e)

        return progress

    def complete_recovery(
        self,
        recovery_id: str,
        success: bool = True,
        error: str | None = None,
    ) -> RecoveryProgress | None:
        """
        Mark a recovery as completed.

        Args:
            recovery_id: ID of the recovery operation
            success: Whether recovery was successful
            error: Error message if not successful

        Returns:
            Final RecoveryProgress or None if not found
        """
        progress = self._active_recoveries.pop(recovery_id, None)
        if not progress:
            logger.warning("Recovery %s not found", recovery_id)
            return None

        progress.phase = RecoveryPhase.COMPLETED if success else RecoveryPhase.FAILED
        progress.percent_complete = 100.0 if success else progress.percent_complete
        progress.error = error

        # Calculate final duration
        duration_seconds = 0.0
        if progress.started_at:
            duration_seconds = (datetime.now(timezone.utc) - progress.started_at).total_seconds()

        # Record completion metrics
        if _recovery_metrics_initialized and RECOVERY_OPERATIONS_TOTAL:
            result = "success" if success else "failure"
            RECOVERY_OPERATIONS_TOTAL.labels(result=result).inc()
            if RECOVERY_DURATION_SECONDS:
                RECOVERY_DURATION_SECONDS.labels(result=result).observe(duration_seconds)

        # Also record in the standard restore metrics
        record_restore_completed(
            duration_seconds=duration_seconds,
            success=success,
            failure_type=error if not success else None,
        )

        # Store in history
        self._completed_recoveries.append(progress)
        if len(self._completed_recoveries) > self._max_history_size:
            self._completed_recoveries = self._completed_recoveries[-self._max_history_size :]

        logger.info(
            "Recovery %s completed: success=%s, duration=%.2fs",
            recovery_id,
            success,
            duration_seconds,
        )

        if self._progress_callback:
            try:
                self._progress_callback(progress)
            except (OSError, RuntimeError, ValueError) as e:
                logger.error("Progress callback failed: %s", e)

        return progress

    def get_progress(self, recovery_id: str) -> RecoveryProgress | None:
        """Get current progress for a recovery operation."""
        return self._active_recoveries.get(recovery_id)

    def get_active_recoveries(self) -> list[RecoveryProgress]:
        """Get all active recovery operations."""
        return list(self._active_recoveries.values())

    def get_recovery_history(self, limit: int = 50) -> list[RecoveryProgress]:
        """Get completed recovery history."""
        return self._completed_recoveries[-limit:]

    def _update_metrics(self, progress: RecoveryProgress) -> None:
        """Update Prometheus metrics for a recovery operation."""
        if not _recovery_metrics_initialized:
            return

        labels = {"recovery_id": progress.recovery_id, "backup_id": progress.backup_id}

        try:
            if RECOVERY_PROGRESS_PERCENT:
                RECOVERY_PROGRESS_PERCENT.labels(**labels).set(progress.percent_complete)

            if RECOVERY_BYTES_PROCESSED:
                RECOVERY_BYTES_PROCESSED.labels(**labels).set(progress.bytes_processed)

            if RECOVERY_OBJECTS_PROCESSED:
                RECOVERY_OBJECTS_PROCESSED.labels(**labels).set(progress.objects_processed)

            if RECOVERY_RATE_BYTES:
                RECOVERY_RATE_BYTES.labels(**labels).set(progress.rate_bytes_per_sec)

            if RECOVERY_RATE_OBJECTS:
                RECOVERY_RATE_OBJECTS.labels(**labels).set(progress.rate_objects_per_sec)

            if RECOVERY_PHASE:
                # Set current phase to 1, others to 0
                for p in RecoveryPhase:
                    value = 1 if p == progress.phase else 0
                    RECOVERY_PHASE.labels(**labels, phase=p.value).set(value)

        except (OSError, RuntimeError, ValueError) as e:
            logger.debug("Failed to update recovery metrics: %s", e)

    def health_check(self) -> dict[str, Any]:
        """
        Health check endpoint for control plane integration.

        Returns:
            Dict with health status suitable for HTTP response
        """
        active_count = len(self._active_recoveries)
        active_list = [p.to_dict() for p in self._active_recoveries.values()]

        return {
            "service": "recovery_monitor",
            "status": "healthy",
            "active_recoveries": active_count,
            "recoveries": active_list,
        }


# =============================================================================
# Global Recovery Monitor Instance
# =============================================================================

_recovery_monitor: RecoveryProgressMonitor | None = None


def get_recovery_monitor() -> RecoveryProgressMonitor:
    """Get or create the global recovery progress monitor."""
    global _recovery_monitor
    if _recovery_monitor is None:
        _recovery_monitor = RecoveryProgressMonitor()
    return _recovery_monitor


def set_recovery_monitor(monitor: RecoveryProgressMonitor | None) -> None:
    """Set the global recovery progress monitor."""
    global _recovery_monitor
    _recovery_monitor = monitor


def record_recovery_progress(
    recovery_id: str,
    backup_id: str,
    phase: RecoveryPhase | None = None,
    bytes_processed: int | None = None,
    objects_processed: int | None = None,
    total_bytes: int | None = None,
    total_objects: int | None = None,
) -> RecoveryProgress | None:
    """
    Convenience function to record recovery progress.

    If recovery doesn't exist, starts it. Otherwise updates it.

    Args:
        recovery_id: Unique identifier for this recovery
        backup_id: ID of the backup being recovered
        phase: Current phase
        bytes_processed: Bytes processed so far
        objects_processed: Objects processed so far
        total_bytes: Total bytes to recover
        total_objects: Total objects to recover

    Returns:
        Current RecoveryProgress
    """
    monitor = get_recovery_monitor()

    # Start if not exists
    if recovery_id not in monitor._active_recoveries:
        return monitor.start_recovery(
            recovery_id=recovery_id,
            backup_id=backup_id,
            total_bytes=total_bytes or 0,
            total_objects=total_objects or 0,
        )

    # Update existing
    return monitor.update_progress(
        recovery_id=recovery_id,
        phase=phase,
        bytes_processed=bytes_processed,
        objects_processed=objects_processed,
        total_bytes=total_bytes,
        total_objects=total_objects,
    )


def record_recovery_completed(
    recovery_id: str,
    success: bool = True,
    error: str | None = None,
) -> RecoveryProgress | None:
    """
    Convenience function to mark a recovery as completed.

    Args:
        recovery_id: ID of the recovery operation
        success: Whether recovery was successful
        error: Error message if not successful

    Returns:
        Final RecoveryProgress
    """
    monitor = get_recovery_monitor()
    return monitor.complete_recovery(recovery_id, success=success, error=error)


__all__ = [
    "record_backup_created",
    "record_backup_verified",
    "record_restore_completed",
    "update_backup_age",
    "get_backup_age_seconds",
    "get_current_metrics",
    "check_rpo_breach",
    "check_rto_breach",
    "get_alerts",
    "BackupMetrics",
    "SLA_TARGETS",
    # Recovery Progress Monitoring
    "RecoveryProgressMonitor",
    "RecoveryProgress",
    "RecoveryPhase",
    "get_recovery_monitor",
    "set_recovery_monitor",
    "record_recovery_progress",
    "record_recovery_completed",
]
