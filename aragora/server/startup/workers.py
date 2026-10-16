"""
Server startup worker initialization.

This module handles SLO webhooks, webhook dispatcher, gauntlet recovery,
durable job queue, gauntlet worker, notification worker,
workflow checkpoint persistence, and backup scheduler initialization.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from aragora.exceptions import REDIS_CONNECTION_ERRORS

if TYPE_CHECKING:
    from aragora.server.workers.gauntlet_worker import GauntletWorker

logger = logging.getLogger(__name__)

# Module-level reference for shutdown coordination
_gauntlet_worker: GauntletWorker | None = None
_testfixer_worker = None
_testfixer_task_worker = None


def get_gauntlet_worker() -> GauntletWorker | None:
    """Get the running gauntlet worker instance (if any).

    Used by the shutdown sequence to gracefully stop the worker
    before closing database connections.
    """
    return _gauntlet_worker


def get_testfixer_worker():
    """Get the running testfixer worker instance (if any)."""
    return _testfixer_worker


def get_testfixer_task_worker():
    """Get the running control-plane testfixer task worker instance (if any)."""
    return _testfixer_task_worker


def sqlite_fallback_skips_store_refusal(refused_store: str, step_store: str) -> bool:
    """Whether a startup step may skip, rather than abort on, a storage-guard refusal.

    True only when the production storage guard refused ``step_store`` itself and
    ARAGORA_ALLOW_SQLITE_FALLBACK is explicitly enabled, parsed as
    ``validate_storage_backend`` (startup/validation.py) and
    ``create_persistent_store`` (storage/connection_factory.py) parse it. The guard
    keeps refusing the store at runtime; only the startup step is skipped.
    """
    if refused_store != step_store:
        return False
    return os.environ.get("ARAGORA_ALLOW_SQLITE_FALLBACK", "").lower() in ("true", "1")


def init_slo_webhooks() -> bool:
    """Initialize SLO violation webhook notifications.

    Connects SLO metric violations to the webhook dispatcher so that
    external alerting systems can be notified of performance degradation.

    Returns:
        True if SLO webhooks were initialized, False otherwise
    """
    try:
        from aragora.observability.metrics.slo import init_slo_webhooks as _init_slo_webhooks

        if _init_slo_webhooks():
            logger.info("SLO webhook notifications enabled")
            return True
        else:
            logger.debug("SLO webhooks not initialized (dispatcher not available)")
            return False

    except ImportError as e:
        logger.debug("SLO webhooks not available: %s", e)
    except (RuntimeError, OSError, ValueError, TypeError) as e:
        logger.warning("Failed to initialize SLO webhooks: %s", e)

    return False


def init_webhook_dispatcher() -> bool:
    """Initialize the webhook dispatcher for outbound notifications.

    Loads webhook configurations from environment and starts the dispatcher.

    Returns:
        True if dispatcher was started, False otherwise
    """
    try:
        from aragora.integrations.webhooks import init_dispatcher

        dispatcher = init_dispatcher()
        if dispatcher:
            logger.info("Webhook dispatcher started with %s endpoint(s)", len(dispatcher.configs))
            return True
        else:
            logger.debug("No webhook configurations found, dispatcher not started")
            return False

    except ImportError as e:
        logger.debug("Webhook dispatcher not available: %s", e)
    except (RuntimeError, OSError, ValueError, TypeError) as e:
        logger.warning("Failed to initialize webhook dispatcher: %s", e)

    return False


def init_gauntlet_run_recovery() -> int:
    """Recover stale gauntlet runs after server restart.

    Finds gauntlet runs that were pending/running when the server stopped
    and marks them as interrupted. Users can then view the status and
    optionally restart them.

    Returns:
        Number of stale runs recovered/marked as interrupted
    """
    if os.environ.get("ARAGORA_DISABLE_GAUNTLET_RECOVERY", "0").lower() in (
        "1",
        "true",
        "yes",
    ):
        logger.debug("Gauntlet run recovery skipped (ARAGORA_DISABLE_GAUNTLET_RECOVERY)")
        return 0

    try:
        from aragora.server.handlers.gauntlet import recover_stale_gauntlet_runs

        recovered = recover_stale_gauntlet_runs(max_age_seconds=7200)
        if recovered > 0:
            logger.info("Recovered %s stale gauntlet runs from previous session", recovered)
        return recovered

    except ImportError as e:
        logger.debug("Gauntlet run recovery not available: %s", e)
    except (RuntimeError, OSError, ValueError, TypeError) as e:
        logger.warning("Failed to recover stale gauntlet runs: %s", e)

    return 0


async def init_durable_job_queue_recovery() -> int:
    """Recover interrupted jobs from the durable job queue.

    This is enabled by default. Set ARAGORA_DURABLE_GAUNTLET=0 to disable.

    Returns:
        Number of jobs recovered and re-enqueued
    """
    import os

    # Enabled by default - set to "0" to disable
    if os.environ.get("ARAGORA_DURABLE_GAUNTLET", "1").lower() in ("0", "false", "no"):
        logger.debug("Durable job queue recovery skipped (ARAGORA_DURABLE_GAUNTLET disabled)")
        return 0

    try:
        # Bound before anything can raise; an ImportError matches the ImportError
        # clause before the DistributedStateError clause is evaluated.
        from aragora.storage.production_guards import DistributedStateError
        from aragora.server.workers.gauntlet_worker import recover_interrupted_gauntlets

        recovered = await recover_interrupted_gauntlets()
        if recovered > 0:
            logger.info("Recovered %s interrupted gauntlet jobs to durable queue", recovered)
        return recovered

    except ImportError as e:
        logger.debug("Durable job queue recovery not available: %s", e)
    except (RuntimeError, OSError, ValueError, TypeError) as e:
        logger.warning("Failed to recover durable job queue: %s", e)
    except DistributedStateError as e:
        if not sqlite_fallback_skips_store_refusal(e.store_name, "job_queue_store"):
            raise
        logger.warning(
            "Durable job queue recovery skipped: storage guard refused %s "
            "(ARAGORA_ALLOW_SQLITE_FALLBACK is set): %s",
            e.store_name,
            e.reason,
        )

    return 0


async def init_gauntlet_worker() -> bool:
    """Initialize and start the gauntlet job queue worker.

    Enabled by default. Set ARAGORA_DURABLE_GAUNTLET=0 to disable.

    The worker instance is stored module-level so the shutdown sequence
    can call ``get_gauntlet_worker().stop()`` before closing database pools.

    Environment Variables:
        ARAGORA_DURABLE_GAUNTLET: "0" to disable (enabled by default)
        ARAGORA_GAUNTLET_WORKERS: Number of concurrent jobs (default: 3)

    Returns:
        True if worker was started, False otherwise
    """
    global _gauntlet_worker
    import os

    # Enabled by default - set to "0" to disable
    if os.environ.get("ARAGORA_DURABLE_GAUNTLET", "1").lower() in ("0", "false", "no"):
        logger.debug("Gauntlet worker not started (ARAGORA_DURABLE_GAUNTLET disabled)")
        return False

    try:
        from aragora.storage.production_guards import DistributedStateError
        from aragora.server.workers.gauntlet_worker import GauntletWorker

        max_concurrent = int(os.environ.get("ARAGORA_GAUNTLET_WORKERS", "3"))
        worker = GauntletWorker(max_concurrent=max_concurrent)

        # Store reference for shutdown coordination
        _gauntlet_worker = worker

        # Start worker in background
        import asyncio

        task = asyncio.create_task(worker.start())
        task.add_done_callback(
            lambda t: logger.error("Gauntlet worker crashed: %s", t.exception())
            if not t.cancelled() and t.exception()
            else None
        )
        logger.info("Gauntlet worker started (max_concurrent=%s)", max_concurrent)
        return True

    except ImportError as e:
        logger.debug("Gauntlet worker not available: %s", e)
    except (RuntimeError, OSError, ValueError, TypeError) as e:
        logger.warning("Failed to start gauntlet worker: %s", e)
    except DistributedStateError as e:
        if not sqlite_fallback_skips_store_refusal(e.store_name, "job_queue_store"):
            raise
        logger.warning(
            "Gauntlet worker not started: storage guard refused %s "
            "(ARAGORA_ALLOW_SQLITE_FALLBACK is set): %s",
            e.store_name,
            e.reason,
        )

    return False


async def init_notification_worker() -> bool:
    """Initialize the notification dispatcher worker for queue processing.

    Starts the background worker that processes queued notifications with
    retry logic, circuit breakers, and dead letter queue support.

    Requires Redis for queue persistence. If Redis is not available, the
    worker will not start but notifications can still be sent synchronously.

    Environment Variables:
        REDIS_URL: Redis connection URL for queue persistence
        ARAGORA_NOTIFICATION_WORKER: Set to "0" to disable (enabled by default)

    Returns:
        True if worker was started, False otherwise
    """
    import os

    # Enabled by default - set to "0" to disable
    if os.environ.get("ARAGORA_NOTIFICATION_WORKER", "1").lower() in ("0", "false", "no"):
        logger.debug("Notification worker not started (ARAGORA_NOTIFICATION_WORKER disabled)")
        return False

    # Check if Redis is available
    redis_url = os.environ.get("REDIS_URL") or os.environ.get("ARAGORA_REDIS_URL")
    if not redis_url:
        logger.debug("Notification worker not started (no REDIS_URL configured)")
        return False

    try:
        import redis.asyncio as aioredis

        from aragora.control_plane.notifications import (
            create_notification_dispatcher,
            NotificationDispatcherConfig,
            set_default_notification_dispatcher,
        )
        from aragora.control_plane.channels import NotificationManager

        # Connect to Redis
        redis_client = aioredis.from_url(redis_url, encoding="utf-8", decode_responses=True)

        # Test connection
        await redis_client.ping()

        # Create manager with Redis persistence and load persisted channel configs
        manager = NotificationManager(redis_client=redis_client)
        channel_count = await manager.load_channels()

        config = NotificationDispatcherConfig(
            queue_enabled=True,
            max_concurrent_deliveries=int(os.environ.get("ARAGORA_NOTIFICATION_CONCURRENCY", "20")),
        )
        dispatcher = create_notification_dispatcher(
            manager=manager,
            redis=redis_client,
            config=config,
        )

        # Start the worker
        await dispatcher.start_worker()
        set_default_notification_dispatcher(dispatcher)

        # Wire dispatcher to task events
        from aragora.control_plane.task_events import set_task_event_dispatcher

        set_task_event_dispatcher(dispatcher)
        logger.info("task_event_dispatcher_wired")

        logger.info(
            "Notification worker started (concurrency=%s, channels_loaded=%s)",
            config.max_concurrent_deliveries,
            channel_count,
        )
        return True

    except ImportError as e:
        logger.debug("Notification worker dependencies not available: %s", e)
    except REDIS_CONNECTION_ERRORS as e:
        logger.warning("Failed to start notification worker: %s", e)
    except (RuntimeError, ValueError, TypeError) as e:
        logger.warning("Failed to start notification worker: %s", e)

    return False


async def init_testfixer_worker() -> bool:
    """Initialize and start the TestFixer worker.

    Environment Variables:
        ARAGORA_TESTFIXER_WORKER: "0" to disable (enabled by default)
    """
    global _testfixer_worker
    if os.environ.get("ARAGORA_TESTFIXER_WORKER", "1").lower() in ("0", "false", "no"):
        logger.debug("TestFixer worker not started (ARAGORA_TESTFIXER_WORKER disabled)")
        return False
    try:
        from aragora.storage.production_guards import DistributedStateError
        from aragora.nomic.testfixer.queue_worker import TestFixerWorker

        worker = TestFixerWorker()
        _testfixer_worker = worker

        import asyncio

        task = asyncio.create_task(worker.start())
        task.add_done_callback(
            lambda t: logger.error("TestFixer worker crashed: %s", t.exception())
            if not t.cancelled() and t.exception()
            else None
        )
        logger.info("TestFixer worker started")
        return True
    except ImportError as e:
        logger.debug("TestFixer worker not available: %s", e)
    except (RuntimeError, OSError, ValueError, TypeError) as e:
        logger.warning("Failed to start TestFixer worker: %s", e)
    except DistributedStateError as e:
        if not sqlite_fallback_skips_store_refusal(e.store_name, "job_queue_store"):
            raise
        logger.warning(
            "TestFixer worker not started: storage guard refused %s "
            "(ARAGORA_ALLOW_SQLITE_FALLBACK is set): %s",
            e.store_name,
            e.reason,
        )
    return False


async def init_testfixer_task_worker() -> bool:
    """Initialize and start the control-plane TestFixer task worker.

    Environment Variables:
        ARAGORA_TESTFIXER_TASK_WORKER: "1" to enable (disabled by default)
    """
    global _testfixer_task_worker
    if os.environ.get("ARAGORA_TESTFIXER_TASK_WORKER", "0").lower() in ("0", "false", "no"):
        logger.debug("TestFixer task worker not started (ARAGORA_TESTFIXER_TASK_WORKER disabled)")
        return False
    try:
        from aragora.nomic.testfixer.worker_loop import start_testfixer_worker

        _testfixer_task_worker = await start_testfixer_worker()
        logger.info("TestFixer task worker started")
        return True
    except ImportError as e:
        logger.debug("TestFixer task worker not available: %s", e)
    except (RuntimeError, OSError, ValueError, TypeError) as e:
        logger.warning("Failed to start TestFixer task worker: %s", e)
    return False


def init_workflow_checkpoint_persistence() -> bool:
    """Wire Knowledge Mound to workflow checkpoint persistence.

    This enables workflow checkpoints to be stored in KnowledgeMound rather
    than local files, providing durable persistence that survives server restarts
    and enables cross-instance checkpoint access.

    Returns:
        True if checkpoint persistence was wired to KnowledgeMound, False if
        falling back to file-based storage.
    """
    try:
        from aragora.knowledge.mound import get_knowledge_mound
        from aragora.workflow.checkpoint_store import set_default_knowledge_mound

        # Get the singleton Knowledge Mound instance
        mound = get_knowledge_mound()

        # Wire it to the checkpoint store
        set_default_knowledge_mound(mound)

        logger.info("Workflow checkpoint persistence wired to KnowledgeMound")
        return True

    except ImportError as e:
        logger.debug("KnowledgeMound not available for checkpoints: %s", e)
    except (RuntimeError, OSError, ValueError, TypeError) as e:
        logger.warning("Failed to wire checkpoint persistence: %s", e)

    return False


async def init_backup_scheduler() -> bool:
    """Initialize the backup scheduler for automated backups and DR drills.

    Starts the backup scheduler that runs scheduled backups at configured
    intervals and performs disaster recovery verification drills.

    Environment Variables:
        BACKUP_ENABLED: Set to "true" to enable backup scheduling (default: false)
        BACKUP_DIR: Directory for backup storage (default: ~/.aragora/backups)
        BACKUP_DAILY_TIME: Time for daily backups in HH:MM format (default: 02:00)
        BACKUP_DR_DRILL_ENABLED: Enable DR drills (default: true)
        BACKUP_DR_DRILL_INTERVAL_DAYS: Days between DR drills (default: 30)

    Returns:
        True if scheduler was started, False otherwise
    """
    import os
    from datetime import time as dt_time

    # Check if backup scheduling is enabled
    if os.environ.get("BACKUP_ENABLED", "false").lower() not in ("true", "1", "yes"):
        logger.debug("Backup scheduler disabled (set BACKUP_ENABLED=true to enable)")
        return False

    try:
        from aragora.backup.manager import get_backup_manager
        from aragora.backup.scheduler import (
            BackupSchedule,
            start_backup_scheduler,
        )

        # Parse configuration from environment
        backup_dir = os.environ.get("BACKUP_DIR")

        # Parse daily backup time (HH:MM format)
        daily_time_str = os.environ.get("BACKUP_DAILY_TIME", "02:00")
        try:
            hour, minute = map(int, daily_time_str.split(":"))
            daily_time = dt_time(hour, minute)
        except (ValueError, TypeError):
            logger.warning("Invalid BACKUP_DAILY_TIME '%s', using 02:00", daily_time_str)
            daily_time = dt_time(2, 0)

        # Parse DR drill settings
        dr_drills_enabled = os.environ.get("BACKUP_DR_DRILL_ENABLED", "true").lower() in (
            "true",
            "1",
            "yes",
        )
        dr_drill_interval = int(os.environ.get("BACKUP_DR_DRILL_INTERVAL_DAYS", "30"))

        # Get or create the backup manager
        manager = get_backup_manager(backup_dir)

        # Create schedule configuration
        schedule = BackupSchedule(
            daily=daily_time,
            enable_dr_drills=dr_drills_enabled,
            dr_drill_interval_days=dr_drill_interval,
        )

        # Start the scheduler
        await start_backup_scheduler(manager, schedule)

        logger.info(
            "Backup scheduler started (daily=%s, dr_drills=%s, dr_interval=%sd)",
            daily_time_str,
            "enabled" if dr_drills_enabled else "disabled",
            dr_drill_interval,
        )
        return True

    except ImportError as e:
        logger.debug("Backup scheduler not available: %s", e)
    except (RuntimeError, OSError, ValueError, TypeError) as e:
        logger.warning("Failed to start backup scheduler: %s", e)

    return False
