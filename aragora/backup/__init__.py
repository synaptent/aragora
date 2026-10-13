"""
Aragora Backup Module.

Provides automated backup with verification:
- SQLite database backups with compression
- Integrity verification (checksums, restore tests)
- Retention policy enforcement
- Prometheus metrics for monitoring
- Automated scheduling with DR drill integration

Quick Start:
    from aragora.backup import BackupManager, get_backup_manager

    # Get the global backup manager
    manager = get_backup_manager()

    # Create a backup
    backup = manager.create_backup("/path/to/database.db")

    # Verify the backup
    result = manager.verify_backup(backup.id)

    # Restore (dry run first)
    manager.restore_backup(backup.id, "/path/to/restore.db", dry_run=True)

Automated Scheduling:
    from aragora.backup import BackupScheduler, BackupSchedule, start_backup_scheduler

    # Create schedule
    schedule = BackupSchedule(
        daily=datetime.time(2, 0),  # 2 AM daily backups
        enable_dr_drills=True,       # Monthly DR drills
    )

    # Start scheduler
    scheduler = await start_backup_scheduler(manager, schedule)
"""

from .manager import (
    BackupManager,
    BackupMetadata,
    BackupStatus,
    BackupType,
    RestoreDrillReport,
    RetentionPolicy,
    VerificationResult,
    get_backup_manager,
    set_backup_manager,
)

from .scheduler import (
    BackupScheduler,
    BackupSchedule,
    BackupJob,
    ScheduleType,
    SchedulerStatus,
    SchedulerStats,
    get_backup_scheduler,
    set_backup_scheduler,
    start_backup_scheduler,
    stop_backup_scheduler,
)
from .encryption import (
    BackupEncryption,
    EncryptionKey,
    EncryptionMetadata,
    KeyManager,
    encrypt_backup,
    decrypt_backup,
)
from .replication_monitor import (
    ReplicationHealthMonitor,
    ReplicationHealth,
    ReplicationConfig,
    ReplicationMetrics,
    ReplicationStatus,
    get_replication_monitor,
    set_replication_monitor,
    create_replication_monitor,
)
from .monitoring import (
    RecoveryProgressMonitor,
    RecoveryProgress,
    RecoveryPhase,
    get_recovery_monitor,
    set_recovery_monitor,
    record_recovery_progress,
    record_recovery_completed,
)
from .offsite import (
    OffsiteBackupConfig,
    OffsiteBackupManager,
    OffsiteBackupRecord,
    RestoreDrillResult,
    IntegrityResult as OffsiteIntegrityResult,
)

__all__ = [
    # Manager
    "BackupManager",
    "BackupMetadata",
    "BackupStatus",
    "BackupType",
    "RestoreDrillReport",
    "RetentionPolicy",
    "VerificationResult",
    "get_backup_manager",
    "set_backup_manager",
    # Scheduler
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
    # Encryption
    "BackupEncryption",
    "EncryptionKey",
    "EncryptionMetadata",
    "KeyManager",
    "encrypt_backup",
    "decrypt_backup",
    # Replication Monitoring
    "ReplicationHealthMonitor",
    "ReplicationHealth",
    "ReplicationConfig",
    "ReplicationMetrics",
    "ReplicationStatus",
    "get_replication_monitor",
    "set_replication_monitor",
    "create_replication_monitor",
    # Recovery Progress Monitoring
    "RecoveryProgressMonitor",
    "RecoveryProgress",
    "RecoveryPhase",
    "get_recovery_monitor",
    "set_recovery_monitor",
    "record_recovery_progress",
    "record_recovery_completed",
    # Offsite Backup
    "OffsiteBackupConfig",
    "OffsiteBackupManager",
    "OffsiteBackupRecord",
    "RestoreDrillResult",
    "OffsiteIntegrityResult",
]
