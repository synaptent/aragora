"""
Server startup initialization tasks.

This module handles the startup sequence for the unified server,
including monitoring, tracing, background tasks, and schedulers.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

# Re-export all public symbols from submodules for backward compatibility
from aragora.server.startup.validation import (
    check_agent_credentials,
    check_connector_dependencies,
    check_production_requirements,
    validate_backend_connectivity,
    validate_database_connectivity,
    validate_redis_connectivity,
    validate_storage_backend,
)
from aragora.server.startup.redis import (
    init_redis_ha,
    init_redis_state_backend,
)
from aragora.server.startup.observability import (
    check_otlp_connectivity,
    init_error_monitoring,
    init_opentelemetry,
    init_otlp_exporter,
    init_prometheus_metrics,
    init_structured_logging,
)
from aragora.server.startup.background import (
    init_background_tasks,
    init_circuit_breaker_persistence,
    init_pulse_scheduler,
    init_settlement_review_scheduler,
    init_self_improvement_daemon,
    init_slack_token_refresh_scheduler,
    init_state_cleanup_task,
    init_stuck_debate_watchdog,
    init_titans_memory_sweep,
)
from aragora.server.startup.control_plane import (
    get_mayor_coordinator,
    get_witness_behavior,
    init_control_plane_coordinator,
    init_mayor_coordinator,
    init_persistent_task_queue,
    init_shared_control_plane_state,
    init_witness_patrol,
)
from aragora.server.startup.knowledge_mound import (
    get_km_config_from_env,
    init_km_adapters,
    init_knowledge_mound_from_env,
    init_tts_integration,
)
from aragora.server.startup.workers import (
    get_gauntlet_worker,
    init_backup_scheduler,
    init_durable_job_queue_recovery,
    init_gauntlet_run_recovery,
    init_gauntlet_worker,
    init_notification_worker,
    init_testfixer_task_worker,
    init_testfixer_worker,
    init_slo_webhooks,
    init_webhook_dispatcher,
    init_workflow_checkpoint_persistence,
)
from aragora.server.startup.dr_drilling import (
    get_dr_drill_scheduler,
    start_dr_drilling,
    stop_dr_drilling,
)
from aragora.server.startup.security import (
    _get_degraded_status,
    init_access_review_scheduler,
    init_approval_gate_recovery,
    init_aws_rotation_monitor,
    init_decision_router,
    init_deployment_validation,
    init_graphql_routes,
    init_api_key_proxy,
    init_key_rotation_scheduler,
    init_mfa_drift_monitor,
    init_rbac_distributed_cache,
    init_secrets_rotation_scheduler,
    validate_required_secrets,
)
from aragora.server.startup.database import (  # noqa: F401
    close_postgres_pool,
    init_postgres_pool,
)
from aragora.server.startup.parallel import (  # noqa: F401
    InitTask,
    ParallelInitializer,
    ParallelInitResult,
    PhaseResult,
    cleanup_on_failure,
    parallel_init,
    run_phase,
)
from aragora.server.startup.validation_runner import (  # noqa: F401
    StartupValidationError,
    run_startup_validation,
    run_startup_validation_sync,
)
from aragora.server.startup.health_check import (  # noqa: F401
    run_startup_health_checks,
)

logger = logging.getLogger(__name__)


async def _validate_config(graceful_degradation: bool) -> None:
    """Phase 1: Run configuration validation (fail fast on misconfigurations)."""
    try:
        from aragora.server.config_validator import ConfigValidator

        config_result = ConfigValidator.validate_all()

        for warning in config_result.warnings:
            logger.warning("Configuration warning: %s", warning)

        if config_result.errors:
            for error in config_result.errors:
                logger.error("Configuration error: %s", error)

            if not graceful_degradation:
                raise RuntimeError(
                    f"Configuration validation failed: {'; '.join(config_result.errors)}"
                )
            else:
                logger.warning(
                    "Configuration errors detected but graceful_degradation enabled. "
                    "Server will start but may not function correctly."
                )
    except ImportError:
        logger.debug("ConfigValidator not available - skipping configuration validation")


async def _validate_prerequisites(
    graceful_degradation: bool,
) -> dict[str, Any] | None:
    """Phase 2: Validate production requirements, OAuth, connectivity, storage.

    Returns a dict with ``connectivity``, ``storage_backend``, ``migration_results``,
    and ``schema_validation`` keys on success, or ``None`` if degraded mode was
    entered (the degraded status has already been set).

    Raises ``RuntimeError`` when ``graceful_degradation`` is False and a check fails.
    """
    import os

    from aragora.control_plane.leader import is_distributed_state_required
    from aragora.server.degraded_mode import DegradedErrorCode, set_degraded

    # --- Production requirements ---
    missing_requirements = check_production_requirements()
    if missing_requirements:
        for req in missing_requirements:
            logger.error("Missing production requirement: %s", req)

        error_msg = f"Production requirements not met: {', '.join(missing_requirements)}"

        if graceful_degradation:
            error_code = DegradedErrorCode.CONFIG_ERROR
            if any("ENCRYPTION_KEY" in r for r in missing_requirements):
                error_code = DegradedErrorCode.ENCRYPTION_KEY_MISSING
            elif any("REDIS" in r for r in missing_requirements):
                error_code = DegradedErrorCode.REDIS_UNAVAILABLE
            elif any("DATABASE" in r for r in missing_requirements):
                error_code = DegradedErrorCode.DATABASE_UNAVAILABLE

            set_degraded(
                reason=error_msg,
                error_code=error_code,
                details={"missing_requirements": missing_requirements},
            )
            return None

        raise RuntimeError(error_msg)

    # --- OAuth configuration ---
    try:
        from aragora.server.handlers.oauth.config import validate_oauth_config

        oauth_missing = validate_oauth_config()
        if oauth_missing:
            logger.warning(
                "[STARTUP] OAuth configuration incomplete: %s. OAuth login may fail.", oauth_missing
            )
    except ImportError:
        logger.debug("OAuth config module not available - skipping OAuth validation")

    # --- Backend connectivity ---
    env = os.environ.get("ARAGORA_ENV", "development")
    is_production = env == "production"
    distributed_required = is_distributed_state_required()
    require_database = os.environ.get("ARAGORA_REQUIRE_DATABASE", "").lower() in (
        "true",
        "1",
        "yes",
    )

    connectivity = await validate_backend_connectivity(
        require_redis=distributed_required,
        require_database=require_database,
        timeout_seconds=10.0 if is_production else 5.0,
    )

    if not connectivity["valid"]:
        for error in connectivity["errors"]:
            logger.error("Backend connectivity failure: %s", error)

        error_msg = f"Backend connectivity validation failed: {'; '.join(connectivity['errors'])}"

        if graceful_degradation:
            error_code = DegradedErrorCode.BACKEND_CONNECTIVITY
            if any("Redis" in e for e in connectivity["errors"]):
                error_code = DegradedErrorCode.REDIS_UNAVAILABLE
            elif any("PostgreSQL" in e for e in connectivity["errors"]):
                error_code = DegradedErrorCode.DATABASE_UNAVAILABLE

            set_degraded(
                reason=error_msg,
                error_code=error_code,
                details={
                    "connectivity": connectivity,
                    "distributed_required": distributed_required,
                    "require_database": require_database,
                },
            )
            return None

        raise RuntimeError(error_msg)

    # --- Storage backend ---
    storage_backend = validate_storage_backend()
    if not storage_backend["valid"]:
        for error in storage_backend["errors"]:
            logger.error("Storage backend error: %s", error)

        error_msg = f"Storage backend validation failed: {'; '.join(storage_backend['errors'])}"

        if graceful_degradation:
            set_degraded(
                reason=error_msg,
                error_code=DegradedErrorCode.DATABASE_UNAVAILABLE,
                details={"storage_backend": storage_backend},
            )
            return None

        raise RuntimeError(error_msg)

    # --- Auto-migrations ---
    migration_results = await _run_migrations(os)

    # --- Schema validation ---
    schema_validation = await _validate_schema(os, graceful_degradation)
    if schema_validation is None:
        return None

    return {
        "connectivity": connectivity,
        "storage_backend": storage_backend,
        "migration_results": migration_results,
        "schema_validation": schema_validation,
    }


async def _run_migrations(os: Any) -> dict[str, Any]:
    """Phase 2b: Run auto-migrations if enabled."""
    migration_results: dict[str, Any] = {"skipped": True}
    auto_migrate_env = os.environ.get("ARAGORA_AUTO_MIGRATE_ON_STARTUP", "").lower()
    if auto_migrate_env == "true":
        should_migrate = True
    elif auto_migrate_env == "false":
        should_migrate = False
    else:
        # Unset — auto-migrate in development environments, skip in production
        env_name = os.environ.get("ARAGORA_ENV", "development").lower()
        should_migrate = env_name in ("development", "dev", "local", "test")
        if should_migrate:
            logger.info(
                "Auto-migrating in %s environment (set ARAGORA_AUTO_MIGRATE_ON_STARTUP=false to disable)",
                env_name,
            )
    if should_migrate:
        try:
            from aragora.server.auto_migrations import run_auto_migrations

            migration_results = await run_auto_migrations()
            if migration_results.get("success"):
                logger.info("Auto-migrations completed successfully")
            elif not migration_results.get("skipped"):
                logger.warning("Auto-migrations had issues: %s", migration_results)
        except (ImportError, OSError, RuntimeError, ValueError) as e:
            logger.error("Auto-migration failed: %s", e)
            migration_results = {"error": "Auto-migration failed", "skipped": False}
    return migration_results


async def _validate_schema(
    os: Any,
    graceful_degradation: bool,
) -> dict[str, Any] | None:
    """Phase 2c: Validate database schema. Returns None if degraded mode entered."""
    from aragora.server.degraded_mode import DegradedErrorCode, set_degraded

    schema_validation: dict[str, Any] = {"success": True, "errors": [], "warnings": []}
    try:
        from aragora.persistence.validator import validate_consolidated_schema

        schema_result = validate_consolidated_schema()
        schema_validation = {
            "success": schema_result.success,
            "errors": schema_result.errors,
            "warnings": schema_result.warnings,
        }

        if not schema_result.success:
            for error in schema_result.errors:
                logger.error("Database schema validation error: %s", error)

            require_valid_schema = os.environ.get("ARAGORA_REQUIRE_VALID_SCHEMA", "").lower() in (
                "true",
                "1",
                "yes",
            )

            if require_valid_schema:
                error_msg = f"Database schema validation failed: {'; '.join(schema_result.errors)}"

                if graceful_degradation:
                    set_degraded(
                        reason=error_msg,
                        error_code=DegradedErrorCode.DATABASE_UNAVAILABLE,
                        details={"schema_validation": schema_validation},
                    )
                    return None

                raise RuntimeError(error_msg)
            else:
                logger.warning(
                    "Database schema validation failed but ARAGORA_REQUIRE_VALID_SCHEMA not set. "
                    "Server will start with potentially incomplete schema. "
                    "Run: python -m aragora.persistence.migrations.consolidate --migrate"
                )
        else:
            for warning in schema_result.warnings:
                logger.warning("Database schema: %s", warning)

    except ImportError:
        logger.debug("Database validator not available - skipping schema validation")

    return schema_validation


def _build_initial_status(
    prereqs: dict[str, Any],
    structured_logging: Any,
    start_time: float,
) -> dict[str, Any]:
    """Build the initial status dict with defaults for all component keys."""
    return {
        "_startup_start_time": start_time,
        "backend_connectivity": prereqs["connectivity"],
        "storage_backend": prereqs["storage_backend"],
        "migrations": prereqs["migration_results"],
        "schema_validation": prereqs["schema_validation"],
        "structured_logging": structured_logging,
        "redis_ha": {"enabled": False, "mode": "standalone", "healthy": False},
        "error_monitoring": False,
        "opentelemetry": False,
        "otlp_exporter": False,
        "prometheus": False,
        "circuit_breakers": 0,
        "background_tasks": False,
        "pulse_scheduler": False,
        "state_cleanup": False,
        "watchdog_task": None,
        "control_plane_coordinator": None,
        "knowledge_mound": False,
        "km_adapters": False,
        "cost_tracker": False,
        "workflow_checkpoint_persistence": False,
        "shared_control_plane_state": False,
        "tts_integration": False,
        "persistent_task_queue": 0,
        "webhook_dispatcher": False,
        "slo_webhooks": False,
        "gauntlet_runs_recovered": 0,
        "durable_jobs_recovered": 0,
        "gauntlet_worker": False,
        "redis_state_backend": False,
        "api_key_proxy": False,
        "key_rotation_scheduler": False,
        "access_review_scheduler": False,
        "rbac_distributed_cache": False,
        "notification_worker": False,
        "graphql": False,
        "backup_scheduler": False,
        "dr_drill_scheduler": False,
        "witness_patrol": False,
        "mayor_coordinator": False,
        "postgres_pool": {"enabled": False},
        "settlement_review_scheduler": False,
        "slack_token_refresh_scheduler": False,
        "titans_memory_sweep": None,
        "budget_notifications": False,
        "spectate_bridge": False,
        "mfa_drift_monitor": False,
    }


async def _init_all_components(
    status: dict[str, Any],
    nomic_dir: Path | None,
    stream_emitter: Any | None,
) -> None:
    """Phase 3: Initialize all server components sequentially."""
    # PostgreSQL connection pool FIRST (event-loop bound, needed by subsystems)
    status["postgres_pool"] = await init_postgres_pool()

    # Redis HA early (other components may depend on it)
    status["redis_ha"] = await init_redis_ha()

    # Observability
    status["error_monitoring"] = await init_error_monitoring()
    status["opentelemetry"] = await init_opentelemetry()
    status["otlp_exporter"] = await init_otlp_exporter()
    status["prometheus"] = await init_prometheus_metrics()

    # Core services with dependencies
    status["circuit_breakers"] = init_circuit_breaker_persistence(nomic_dir)
    status["background_tasks"] = init_background_tasks(nomic_dir)
    status["pulse_scheduler"] = await init_pulse_scheduler(stream_emitter)
    status["state_cleanup"] = init_state_cleanup_task()
    status["watchdog_task"] = await init_stuck_debate_watchdog()
    status["control_plane_coordinator"] = await init_control_plane_coordinator()
    status["shared_control_plane_state"] = await init_shared_control_plane_state()

    # Witness Patrol for Gas Town agent monitoring
    status["witness_patrol"] = await init_witness_patrol()

    # Mayor Coordinator for distributed leadership
    status["mayor_coordinator"] = await init_mayor_coordinator()

    # Knowledge and workflow
    status["knowledge_mound"] = await init_knowledge_mound_from_env()
    status["km_adapters"] = await init_km_adapters()

    # Process any failed KM ingestions from previous runs
    try:
        from aragora.knowledge.mound.ingestion_queue import IngestionDeadLetterQueue

        dlq = IngestionDeadLetterQueue()
        failed_items = dlq.list_failed(limit=100)
        if failed_items:
            logger.info(
                "Found %d items in KM ingestion dead letter queue, processing...",
                len(failed_items),
            )
            try:
                from aragora.knowledge.mound import get_knowledge_mound

                km = get_knowledge_mound()

                def _retry_ingest(result_dict: dict) -> None:
                    """Re-ingest a debate result dict into the Knowledge Mound."""
                    debate_id = result_dict.get("debate_id", "unknown")
                    conclusion = result_dict.get("conclusion", "")
                    if conclusion and hasattr(km, "store_sync"):
                        km.store_sync(
                            content=conclusion,
                            metadata={"debate_id": debate_id, "source": "dlq_retry"},
                        )

                succeeded = dlq.process_queue(ingest_fn=_retry_ingest)
                still_failing = len(failed_items) - succeeded
                logger.info(
                    "DLQ processing complete: %d retried, %d succeeded, %d still failing",
                    len(failed_items),
                    succeeded,
                    still_failing,
                )
            except (ImportError, AttributeError):
                logger.debug("KM not available for DLQ retry, items preserved for next startup")
        status["ingestion_dlq"] = True
    except ImportError:
        logger.debug("Ingestion DLQ module not available")
        status["ingestion_dlq"] = False
    except (OSError, RuntimeError, ValueError) as e:
        logger.debug("Ingestion DLQ processing failed: %s", e)
        status["ingestion_dlq"] = False

    # Cost tracking (after KM so it can wire the KM adapter)
    try:
        from aragora.billing.cost_tracker import get_cost_tracker

        tracker = get_cost_tracker()
        status["cost_tracker"] = getattr(tracker, "_km_adapter", None) is not None
        if getattr(tracker, "_km_adapter", None):
            logger.info("CostTracker initialized with KM adapter")
        else:
            logger.info("CostTracker initialized (without KM adapter)")
    except ImportError:
        logger.debug("CostTracker not available")
        status["cost_tracker"] = False
    except (OSError, RuntimeError, ValueError) as e:
        logger.warning("CostTracker initialization failed: %s", e)
        status["cost_tracker"] = False

    # Budget alert notifications (after cost tracking)
    try:
        from aragora.server.initialization import init_budget_notifications

        status["budget_notifications"] = init_budget_notifications()
    except ImportError:
        logger.debug("Budget notification init not available")
        status["budget_notifications"] = False

    status["workflow_checkpoint_persistence"] = init_workflow_checkpoint_persistence()
    status["tts_integration"] = await init_tts_integration()
    status["persistent_task_queue"] = await init_persistent_task_queue()

    # Webhooks (dispatcher must be initialized before SLO webhooks)
    status["webhook_dispatcher"] = init_webhook_dispatcher()
    status["slo_webhooks"] = init_slo_webhooks()

    # Recovery
    status["gauntlet_runs_recovered"] = init_gauntlet_run_recovery()
    status["durable_jobs_recovered"] = await init_durable_job_queue_recovery()

    # Workers and schedulers
    status["gauntlet_worker"] = await init_gauntlet_worker()
    status["backup_scheduler"] = await init_backup_scheduler()
    dr_scheduler = await start_dr_drilling()
    status["dr_drill_scheduler"] = dr_scheduler is not None
    status["notification_worker"] = await init_notification_worker()
    status["testfixer_worker"] = await init_testfixer_worker()
    status["testfixer_task_worker"] = await init_testfixer_task_worker()
    status["settlement_review_scheduler"] = await init_settlement_review_scheduler()
    status["slack_token_refresh_scheduler"] = await init_slack_token_refresh_scheduler()
    status["titans_memory_sweep"] = await init_titans_memory_sweep()
    status["self_improvement_daemon"] = await init_self_improvement_daemon()

    # Scaling and routing
    status["redis_state_backend"] = await init_redis_state_backend()
    status["decision_router"] = await init_decision_router()

    # Security and secrets
    secrets_validation = validate_required_secrets()
    status["secrets_validation"] = secrets_validation
    if not secrets_validation["valid"]:
        for error in secrets_validation["errors"]:
            logger.error("Secrets validation: %s", error)
    for warning in secrets_validation.get("warnings", []):
        logger.warning("Secrets validation: %s", warning)

    status["api_key_proxy"] = await init_api_key_proxy()
    status["key_rotation_scheduler"] = await init_key_rotation_scheduler()
    status["secrets_rotation_scheduler"] = await init_secrets_rotation_scheduler()
    status["aws_rotation_monitor"] = await init_aws_rotation_monitor()
    status["access_review_scheduler"] = await init_access_review_scheduler()
    status["rbac_distributed_cache"] = await init_rbac_distributed_cache()
    status["approval_gate_recovery"] = await init_approval_gate_recovery()
    status["mfa_drift_monitor"] = await init_mfa_drift_monitor()

    # Spectate WebSocket bridge (lightweight, no external deps)
    try:
        from aragora.spectate.ws_bridge import get_spectate_bridge

        bridge = get_spectate_bridge()
        bridge.start()
        status["spectate_bridge"] = bridge.running
        if bridge.running:
            logger.info("SpectateWebSocketBridge started")
    except ImportError:
        logger.debug("Spectate bridge module not available")
        status["spectate_bridge"] = False
    except (RuntimeError, OSError, ValueError) as e:
        logger.warning("SpectateWebSocketBridge initialization failed: %s", e)
        status["spectate_bridge"] = False

    # API and deployment
    status["graphql"] = init_graphql_routes(None)
    status["deployment_validation"] = await init_deployment_validation()


def _generate_startup_report(status: dict[str, Any]) -> None:
    """Phase 4: Record startup metrics and generate a report."""
    import time as time_mod

    startup_end_time = time_mod.time()
    startup_duration = startup_end_time - (status.get("_startup_start_time", startup_end_time))

    try:
        from aragora.server.startup_transaction import (
            StartupReport,
            set_last_startup_report,
        )

        components_initialized = [k for k, v in status.items() if v and not k.startswith("_")]
        components_failed = [k for k, v in status.items() if v is False]

        report = StartupReport(
            success=len(components_failed) == 0,
            total_duration_seconds=startup_duration,
            slo_seconds=30.0,
            slo_met=startup_duration <= 30.0,
            components_initialized=len(components_initialized),
            components_failed=components_failed,
            checkpoints=[],
            error=None,
        )
        set_last_startup_report(report)

        if startup_duration > 30.0:
            logger.warning(
                f"[STARTUP] Completed in {startup_duration:.2f}s (exceeds 30s SLO target)"
            )
        else:
            logger.info(
                f"[STARTUP] Completed in {startup_duration:.2f}s "
                f"({len(components_initialized)} components)"
            )

        status["startup_report"] = report.to_dict()

    except ImportError:
        logger.debug("startup_transaction module not available - skipping report")
        status["startup_duration_seconds"] = round(startup_duration, 2)


async def run_startup_sequence(
    nomic_dir: Path | None = None,
    stream_emitter: Any | None = None,
    graceful_degradation: bool = True,
) -> dict:
    """Run the full server startup sequence.

    Args:
        nomic_dir: Path to nomic directory
        stream_emitter: Optional event emitter for debates
        graceful_degradation: If True, enter degraded mode on failure instead of crashing.
            The server will start but return 503 for most endpoints until the issue is resolved.
            Defaults to True for production resilience.

    Environment Variables:
        ARAGORA_STRICT_STARTUP: If set to "true", overrides graceful_degradation to False,
            causing the server to fail fast if dependencies are unavailable.
            Useful for Kubernetes deployments where you want pods to restart on failure.

    Returns:
        Dictionary with startup status for each component. If graceful_degradation is True
        and startup fails, returns a minimal status dict with degraded=True.

    Raises:
        RuntimeError: If production requirements are not met AND graceful_degradation is False
    """
    import os
    import time as time_mod

    # STRICT_STARTUP mode: Override graceful_degradation to fail fast
    strict_startup = os.environ.get("ARAGORA_STRICT_STARTUP", "").lower() in ("1", "true", "yes")
    if strict_startup:
        logger.info("ARAGORA_STRICT_STARTUP enabled: server will fail fast on dependency errors")
        graceful_degradation = False

    # Phase 1: Configuration validation
    await _validate_config(graceful_degradation)

    # Phase 2: Prerequisites (requirements, connectivity, storage, migrations, schema)
    prereqs = await _validate_prerequisites(graceful_degradation)
    if prereqs is None:
        return _get_degraded_status()

    # Phase 3: Initialize all components
    structured_logging = init_structured_logging()
    status = _build_initial_status(prereqs, structured_logging, time_mod.time())
    await _init_all_components(status, nomic_dir, stream_emitter)

    # Phase 4: Generate startup report
    _generate_startup_report(status)

    return status


__all__ = [
    "check_connector_dependencies",
    "check_agent_credentials",
    "check_production_requirements",
    "validate_redis_connectivity",
    "validate_database_connectivity",
    "validate_backend_connectivity",
    "validate_storage_backend",
    "init_redis_ha",
    "init_error_monitoring",
    "init_opentelemetry",
    "init_otlp_exporter",
    "init_prometheus_metrics",
    "init_circuit_breaker_persistence",
    "init_background_tasks",
    "init_pulse_scheduler",
    "init_state_cleanup_task",
    "init_stuck_debate_watchdog",
    "init_settlement_review_scheduler",
    "init_debate_settlement_scheduler",
    "init_slack_token_refresh_scheduler",
    "init_titans_memory_sweep",
    "init_self_improvement_daemon",
    "init_control_plane_coordinator",
    "init_shared_control_plane_state",
    "init_tts_integration",
    "init_persistent_task_queue",
    "init_km_adapters",
    "init_workflow_checkpoint_persistence",
    "init_backup_scheduler",
    "init_webhook_dispatcher",
    "init_slo_webhooks",
    "init_gauntlet_run_recovery",
    "init_durable_job_queue_recovery",
    "init_gauntlet_worker",
    "get_gauntlet_worker",
    "init_testfixer_worker",
    "init_testfixer_task_worker",
    "init_redis_state_backend",
    "init_decision_router",
    "init_aws_rotation_monitor",
    "init_api_key_proxy",
    "init_key_rotation_scheduler",
    "init_mfa_drift_monitor",
    "init_access_review_scheduler",
    "init_rbac_distributed_cache",
    "init_approval_gate_recovery",
    "init_notification_worker",
    "init_graphql_routes",
    "init_deployment_validation",
    "init_witness_patrol",
    "get_witness_behavior",
    "init_mayor_coordinator",
    "get_mayor_coordinator",
    "start_dr_drilling",
    "stop_dr_drilling",
    "get_dr_drill_scheduler",
    "run_startup_sequence",
    "get_km_config_from_env",
    "init_knowledge_mound_from_env",
    # Parallel initialization
    "parallel_init",
    "ParallelInitializer",
    "ParallelInitResult",
    "PhaseResult",
    "InitTask",
    "run_phase",
    "cleanup_on_failure",
    # Startup validation
    "StartupValidationError",
    "run_startup_validation",
    "run_startup_validation_sync",
    # Observability
    "check_otlp_connectivity",
    "init_structured_logging",
]
