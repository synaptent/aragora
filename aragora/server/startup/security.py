"""
Server startup security initialization.

This module handles deployment validation, GraphQL routes, RBAC distributed cache,
approval gate recovery, access review scheduler, key rotation scheduler,
and decision router initialization.
"""

import logging
from typing import Any

from aragora.exceptions import REDIS_CONNECTION_ERRORS

logger = logging.getLogger(__name__)


def _get_degraded_status() -> dict[str, Any]:
    """Return a minimal status dict for degraded mode startup.

    This allows the server to start in degraded mode where it can
    respond to health checks but returns 503 for other endpoints.
    """
    return {
        "degraded": True,
        "backend_connectivity": {"valid": False, "errors": ["Server in degraded mode"]},
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
        "km_adapters": False,
        "workflow_checkpoint_persistence": False,
        "shared_control_plane_state": False,
        "tts_integration": False,
        "persistent_task_queue": 0,
        "webhook_dispatcher": False,
        "slo_webhooks": False,
        "gauntlet_runs_recovered": 0,
        "durable_jobs_recovered": 0,
        "gauntlet_worker": False,
        "settlement_review_scheduler": False,
        "redis_state_backend": False,
        "key_rotation_scheduler": False,
        "access_review_scheduler": False,
        "rbac_distributed_cache": False,
        "notification_worker": False,
        "graphql": False,
        "backup_scheduler": False,
    }


async def init_deployment_validation() -> dict:
    """Run comprehensive deployment validation and log results.

    This validates all production requirements including:
    - JWT secret strength and uniqueness
    - AI provider API key configuration
    - Database connectivity (Supabase/PostgreSQL)
    - Redis configuration for distributed state
    - CORS and security settings
    - Rate limiting configuration
    - TLS/HTTPS settings
    - Encryption key configuration

    When ``ARAGORA_STRICT_DEPLOYMENT=true`` is set, the server will refuse
    to start if any critical validation issues are found.

    Returns:
        Dictionary with validation results summary

    Raises:
        DeploymentNotReadyError: When strict mode is enabled and
            critical issues are detected.
    """
    import os

    try:
        from aragora.ops.deployment_validator import validate_deployment, Severity

        env = os.environ.get("ARAGORA_ENV", "development")
        is_production = env in ("production", "staging")

        # Default to strict mode in production/staging environments
        strict_env = os.environ.get("ARAGORA_STRICT_DEPLOYMENT", "")
        if strict_env:
            strict = strict_env.lower() in ("true", "1", "yes")
        else:
            strict = is_production

        if is_production and not strict:
            logger.warning(
                "ARAGORA_STRICT_DEPLOYMENT is disabled in production - "
                "this is not recommended. Server may start with insecure configuration."
            )

        result = await validate_deployment(strict=strict)

        # Log validation results
        critical_count = sum(1 for i in result.issues if i.severity == Severity.CRITICAL)
        warning_count = sum(1 for i in result.issues if i.severity == Severity.WARNING)
        info_count = sum(1 for i in result.issues if i.severity == Severity.INFO)

        if result.ready:
            if warning_count > 0:
                logger.info(
                    f"[DEPLOYMENT VALIDATION] Passed with {warning_count} warning(s), "
                    f"{info_count} info message(s). Duration: {result.validation_duration_ms:.1f}ms"
                )
            else:
                logger.info(
                    f"[DEPLOYMENT VALIDATION] All checks passed. "
                    f"Duration: {result.validation_duration_ms:.1f}ms"
                )
        else:
            logger.warning(
                "[DEPLOYMENT VALIDATION] %s critical issue(s), %s warning(s). Server may not function correctly.",
                critical_count,
                warning_count,
            )

        # Log critical issues
        for issue in result.issues:
            if issue.severity == Severity.CRITICAL:
                logger.error(
                    "[DEPLOYMENT VALIDATION] CRITICAL - %s: %s", issue.component, issue.message
                )
                if issue.suggestion:
                    logger.error("  Suggestion: %s", issue.suggestion)
            elif issue.severity == Severity.WARNING:
                logger.warning(
                    "[DEPLOYMENT VALIDATION] WARNING - %s: %s", issue.component, issue.message
                )

        return {
            "ready": result.ready,
            "live": result.live,
            "critical_issues": critical_count,
            "warnings": warning_count,
            "info_messages": info_count,
            "validation_duration_ms": result.validation_duration_ms,
            "components_checked": len(result.components),
        }

    except ImportError as e:
        logger.debug("Deployment validator not available: %s", e)
        return {"available": False, "error": "Deployment validator not available"}
    except (RuntimeError, OSError, ValueError) as e:
        logger.warning("Deployment validation failed: %s", e)
        return {"available": True, "error": "Deployment validation failed"}


def init_graphql_routes(app: Any) -> bool:
    """Initialize GraphQL routes and mount endpoints.

    Mounts the GraphQL API endpoint at /graphql and the GraphiQL playground
    at /graphiql (when enabled). The routes are only mounted if GraphQL is
    enabled via ARAGORA_GRAPHQL_ENABLED environment variable.

    Args:
        app: The application or handler registry to mount routes on.
              For UnifiedServer, this is typically the handler registry.

    Environment Variables:
        ARAGORA_GRAPHQL_ENABLED: Enable GraphQL API (default: true)
        ARAGORA_GRAPHQL_INTROSPECTION: Allow schema introspection (default: true in dev, false in prod)
        ARAGORA_GRAPHIQL_ENABLED: Enable GraphiQL playground (default: same as dev mode)

    Returns:
        True if GraphQL routes were mounted, False otherwise
    """
    import os

    # Check if GraphQL is enabled
    graphql_enabled = os.environ.get("ARAGORA_GRAPHQL_ENABLED", "true").lower() in (
        "true",
        "1",
        "yes",
        "on",
    )

    if not graphql_enabled:
        logger.info("GraphQL API disabled (ARAGORA_GRAPHQL_ENABLED=false)")
        return False

    try:
        from aragora.server.graphql import GraphQLHandler, GraphQLSchemaHandler  # noqa: F401

        # Determine environment for defaults
        env = os.environ.get("ARAGORA_ENV", "development")
        is_production = env == "production"

        # Check introspection and GraphiQL settings
        introspection_default = "false" if is_production else "true"
        introspection_enabled = os.environ.get(
            "ARAGORA_GRAPHQL_INTROSPECTION", introspection_default
        ).lower() in ("true", "1", "yes", "on")

        graphiql_default = "false" if is_production else "true"
        graphiql_enabled = os.environ.get("ARAGORA_GRAPHIQL_ENABLED", graphiql_default).lower() in (
            "true",
            "1",
            "yes",
            "on",
        )

        # Log configuration
        logger.info(
            "GraphQL API enabled (introspection=%s, graphiql=%s)",
            introspection_enabled,
            graphiql_enabled,
        )

        # The handlers are auto-registered via the handler registry pattern
        # when they define ROUTES class attribute. We just need to ensure
        # they can be imported and the module is loaded.

        # Log mounted endpoints
        logger.info("  POST /graphql - GraphQL query endpoint")
        logger.info("  POST /api/graphql - GraphQL query endpoint (alternate)")
        logger.info("  POST /api/v1/graphql - GraphQL query endpoint (versioned)")

        if introspection_enabled:
            logger.info("  GET /graphql/schema - Schema introspection endpoint")

        if graphiql_enabled:
            logger.info("  GET /graphql - GraphiQL playground")

        return True

    except ImportError as e:
        logger.debug("GraphQL module not available: %s", e)
        return False
    except (RuntimeError, OSError, ValueError) as e:
        logger.warning("Failed to initialize GraphQL routes: %s", e)
        return False


async def init_rbac_distributed_cache() -> bool:
    """Initialize Redis-backed RBAC cache for distributed deployments.

    Enables cross-instance RBAC decision caching for horizontal scaling.
    Only initializes if Redis is available.

    Environment Variables:
        REDIS_URL: Redis connection URL
        RBAC_CACHE_ENABLED: Set to "false" to disable (default: true)
        RBAC_CACHE_DECISION_TTL: Cache TTL for decisions (default: 300s)
        RBAC_CACHE_L1_ENABLED: Enable local L1 cache (default: true)

    Returns:
        True if distributed cache was initialized, False otherwise
    """
    import os

    # Check if RBAC cache is enabled
    if os.environ.get("RBAC_CACHE_ENABLED", "true").lower() == "false":
        logger.debug("RBAC distributed cache disabled (RBAC_CACHE_ENABLED=false)")
        return False

    # Check if Redis URL is configured
    redis_url = os.environ.get("REDIS_URL") or os.environ.get("ARAGORA_REDIS_URL")
    if not redis_url:
        logger.debug("RBAC distributed cache not initialized (no REDIS_URL)")
        return False

    try:
        from aragora.rbac.cache import (
            RBACCacheConfig,
            RBACDistributedCache,  # noqa: F401
            get_rbac_cache,
        )
        from aragora.rbac.checker import (
            PermissionChecker,
            get_permission_checker,
            set_permission_checker,
        )

        # Create cache config from environment
        config = RBACCacheConfig.from_env()

        # Initialize distributed cache
        cache = get_rbac_cache(config)
        cache.start()

        # Check if Redis is actually available
        if not cache.is_distributed:
            logger.debug("RBAC cache Redis not available, using local-only")
            return False

        # Create new permission checker with distributed cache backend
        current_checker = get_permission_checker()
        new_checker = PermissionChecker(
            auditor=current_checker._auditor if hasattr(current_checker, "_auditor") else None,
            cache_ttl=config.decision_ttl_seconds,
            enable_cache=True,
            cache_backend=cache,
        )
        set_permission_checker(new_checker)

        logger.info(
            "RBAC distributed cache initialized (decision_ttl=%ss, l1=%s)",
            config.decision_ttl_seconds,
            "enabled" if config.l1_enabled else "disabled",
        )
        return True

    except ImportError as e:
        logger.debug("RBAC distributed cache not available: %s", e)
    except REDIS_CONNECTION_ERRORS as e:
        logger.warning("Failed to initialize RBAC distributed cache: %s", e)
    except RuntimeError as e:
        logger.warning("Failed to initialize RBAC distributed cache: %s", e)

    return False


async def init_approval_gate_recovery() -> int:
    """Recover pending approval requests from the governance store.

    Restores any pending approval requests that were active when the server
    last stopped. Approvals that have expired since then are automatically
    marked as expired.

    Returns:
        Number of pending approvals recovered
    """
    try:
        from aragora.server.middleware.approval_gate import recover_pending_approvals

        recovered = await recover_pending_approvals()
        if recovered > 0:
            logger.info("Recovered %s pending approval requests", recovered)
        return recovered

    except ImportError as e:
        logger.debug("Approval gate recovery not available: %s", e)
        return 0
    except (OSError, RuntimeError, ValueError) as e:
        logger.warning("Failed to recover pending approvals: %s", e)
        return 0


async def init_access_review_scheduler() -> bool:
    """Initialize the access review scheduler for SOC 2 compliance.

    Starts the scheduler that runs periodic access reviews:
    - Monthly user access reviews
    - Weekly stale credential detection (90+ days unused)
    - Role certification workflows
    - Manager sign-off requirements

    SOC 2 Compliance: CC6.1, CC6.2 (Access Control)

    Environment Variables:
        ARAGORA_ACCESS_REVIEW_ENABLED: Set to "true" to enable (default: true in production)
        ARAGORA_ACCESS_REVIEW_STORAGE: Path for SQLite storage (default: ARAGORA_DATA_DIR/access_reviews.db)

    Returns:
        True if scheduler was started, False otherwise
    """
    import os

    enabled = os.environ.get("ARAGORA_ACCESS_REVIEW_ENABLED", "").lower() in (
        "true",
        "1",
        "yes",
    )
    is_production = os.environ.get("ARAGORA_ENV", "development") == "production"

    # Enable by default in production
    if not enabled and is_production:
        enabled = True

    if not enabled:
        logger.debug(
            "Access review scheduler disabled (set ARAGORA_ACCESS_REVIEW_ENABLED=true to enable)"
        )
        return False

    try:
        from aragora.scheduler.access_review_scheduler import (
            AccessReviewConfig,
            get_access_review_scheduler,
        )

        # Configure storage path
        storage_path = os.environ.get("ARAGORA_ACCESS_REVIEW_STORAGE")
        if not storage_path:
            from aragora.persistence.db_config import get_nomic_dir

            data_dir = get_nomic_dir()
            data_dir.mkdir(parents=True, exist_ok=True)
            storage_path = str(data_dir / "access_reviews.db")

        config = AccessReviewConfig(storage_path=storage_path)

        # Get or create the global scheduler
        scheduler = get_access_review_scheduler(config)

        # Start the scheduler
        await scheduler.start()

        logger.info(
            "Access review scheduler started (storage=%s, monthly_review_day=%s)",
            storage_path,
            config.monthly_review_day,
        )
        return True

    except ImportError as e:
        logger.debug("Access review scheduler not available: %s", e)
        return False
    except (OSError, RuntimeError, ValueError) as e:
        logger.warning("Failed to start access review scheduler: %s", e)
        return False


async def init_key_rotation_scheduler() -> bool:
    """Initialize the key rotation scheduler for automated key management.

    Starts the scheduler that automatically rotates encryption keys based on
    configured intervals and handles re-encryption of data if enabled.

    Environment Variables:
        ARAGORA_KEY_ROTATION_ENABLED: Set to "true" to enable (default: false in dev, true in prod)
        ARAGORA_KEY_ROTATION_INTERVAL_DAYS: Days between rotations (default: 90)
        ARAGORA_KEY_ROTATION_OVERLAP_DAYS: Days to keep old keys valid (default: 7)
        ARAGORA_KEY_ROTATION_RE_ENCRYPT: Re-encrypt data after rotation (default: false)
        ARAGORA_KEY_ROTATION_ALERT_DAYS: Days before rotation to alert (default: 7)

    Returns:
        True if scheduler was started, False otherwise
    """
    import os

    # In production, enabled by default; in development, disabled by default
    env = os.environ.get("ARAGORA_ENV", "development")
    default_enabled = "true" if env == "production" else "false"
    enabled = os.environ.get("ARAGORA_KEY_ROTATION_ENABLED", default_enabled).lower() == "true"

    if not enabled:
        logger.debug(
            "Key rotation scheduler disabled (set ARAGORA_KEY_ROTATION_ENABLED=true to enable)"
        )
        return False

    # Check if encryption key is configured
    if not os.environ.get("ARAGORA_ENCRYPTION_KEY"):
        logger.debug("Key rotation scheduler not started (no ARAGORA_ENCRYPTION_KEY configured)")
        return False

    try:
        from aragora.ops.key_rotation import (
            get_key_rotation_scheduler,
            KeyRotationConfig,
        )
        from aragora.observability.metrics.security import set_active_keys

        # Create scheduler with config from environment
        config = KeyRotationConfig.from_env()
        scheduler = get_key_rotation_scheduler()
        scheduler.config = config

        # Set up alert callback to integrate with notification systems
        def alert_callback(severity: str, message: str, details: dict) -> None:
            """Forward key rotation alerts to notification systems."""
            try:
                from aragora.integrations.webhooks import get_webhook_dispatcher

                dispatcher = get_webhook_dispatcher()
                if dispatcher:
                    dispatcher.enqueue(
                        {
                            "type": "security.key_rotation",
                            "severity": severity,
                            "message": message,
                            **details,
                        }
                    )
            except (ImportError, ConnectionError, OSError, RuntimeError) as e:
                # Broad catch intentional: alert delivery should never break key rotation
                logger.warning("Failed to dispatch key rotation alert: %s", e)

        scheduler.alert_callback = alert_callback

        # Start the scheduler
        await scheduler.start()

        # Also initialize the security module's scheduler for health endpoint visibility
        try:
            from aragora.security.key_rotation import (
                get_or_create_key_rotation_scheduler,
                KeyRotationConfig as SecurityKeyRotationConfig,
            )

            sec_scheduler = get_or_create_key_rotation_scheduler()
            sec_scheduler.config = SecurityKeyRotationConfig.from_env()
            await sec_scheduler.start()
        except (ImportError, RuntimeError, OSError) as e:
            logger.debug("Security key rotation scheduler not started: %s", e)

        # Set initial key metrics
        try:
            from aragora.security.encryption import get_encryption_service

            service = get_encryption_service()
            active_key_id = service.get_active_key_id()
            if active_key_id:
                set_active_keys(master=1)
        except (ImportError, RuntimeError, AttributeError) as e:
            logger.debug("Could not set initial key metrics: %s", e)

        # Get initial status for logging
        status = await scheduler.get_status()
        next_rotation = status.get("next_rotation", "unknown")

        logger.info(
            "Key rotation scheduler started (interval=%sd, overlap=%sd, re_encrypt=%s)",
            config.rotation_interval_days,
            config.key_overlap_days,
            config.re_encrypt_on_rotation,
        )

        if next_rotation and next_rotation != "unknown":
            logger.info("Next key rotation scheduled: %s", next_rotation)

        return True

    except ImportError as e:
        logger.debug("Key rotation scheduler not available: %s", e)
    except (OSError, RuntimeError, ValueError) as e:
        logger.warning("Failed to start key rotation scheduler: %s", e)

    return False


async def init_secrets_rotation_scheduler() -> bool:
    """Initialize the secrets rotation scheduler for automated API key management.

    Starts the scheduler that automatically rotates API keys, JWT secrets,
    and other credentials based on configured intervals. Integrates with
    AWS Secrets Manager when available.

    Environment Variables:
        ARAGORA_SECRETS_ROTATION_ENABLED: Set to "true" to enable
        ARAGORA_SECRETS_ROTATION_INTERVAL_DAYS: Days between rotations (default: 90)

    Returns:
        True if scheduler was started, False otherwise
    """
    import os

    env = os.environ.get("ARAGORA_ENV", "development")
    default_enabled = "true" if env == "production" else "false"
    enabled = os.environ.get("ARAGORA_SECRETS_ROTATION_ENABLED", default_enabled).lower() == "true"

    if not enabled:
        logger.debug(
            "Secrets rotation scheduler disabled "
            "(set ARAGORA_SECRETS_ROTATION_ENABLED=true to enable)"
        )
        return False

    try:
        from aragora.scheduler.secrets_rotation_scheduler import (
            get_secrets_rotation_scheduler,
        )

        scheduler = get_secrets_rotation_scheduler()
        await scheduler.start()

        logger.info("Secrets rotation scheduler started")
        return True

    except ImportError as e:
        logger.debug("Secrets rotation scheduler not available: %s", e)
    except (OSError, RuntimeError, ValueError) as e:
        logger.warning("Failed to start secrets rotation scheduler: %s", e)

    return False


async def init_api_key_proxy() -> bool:
    """Initialize the API Key Proxy with frequency-hopping rotation.

    Starts the proxy that securely manages third-party API keys with
    jittered rotation schedules, usage anomaly detection, and audit logging.

    Covered services:
        - ElevenLabs (6h jittered) — TTS voice synthesis
        - Gemini (4h jittered) — Google AI inference
        - fal.ai (6h jittered) — Image/video generation
        - Mistral (8h jittered) — Mistral AI inference
        - OpenRouter (12h jittered) — Fallback LLM routing
        - xAI/Grok (8h jittered) — xAI inference
        - DeepSeek (8h jittered) — DeepSeek inference
        - Stripe (weekly jittered) — Payment processing
        - Anthropic (anomaly detection only) — No programmatic rotation
        - OpenAI (anomaly detection only) — No programmatic rotation

    Environment Variables:
        ARAGORA_API_KEY_PROXY_ENABLED: Set to "true" to enable (default: true in prod)

    Returns:
        True if proxy was started, False otherwise
    """
    import os

    env = os.environ.get("ARAGORA_ENV", "development")
    default_enabled = "true" if env == "production" else "false"
    enabled = os.environ.get("ARAGORA_API_KEY_PROXY_ENABLED", default_enabled).lower() == "true"

    if not enabled:
        logger.debug("API key proxy disabled (set ARAGORA_API_KEY_PROXY_ENABLED=true to enable)")
        return False

    try:
        from aragora.security.api_key_proxy import get_api_key_proxy

        proxy = get_api_key_proxy()

        # Import rotation handlers to trigger auto-registration
        rotator_modules = [
            ("aragora.security.elevenlabs_rotator", "ElevenLabs"),
            ("aragora.security.gemini_rotator", "Gemini"),
            ("aragora.security.fal_rotator", "fal.ai"),
            ("aragora.security.mistral_rotator", "Mistral"),
            ("aragora.security.openrouter_rotator", "OpenRouter"),
            ("aragora.security.xai_rotator", "xAI"),
            ("aragora.security.deepseek_rotator", "DeepSeek"),
            ("aragora.security.stripe_rotator", "Stripe"),
        ]
        for module_path, name in rotator_modules:
            try:
                __import__(module_path)
            except ImportError:
                logger.debug("%s rotator not available", name)

        # Start the proxy (begins rotation scheduler)
        await proxy.start()

        # Log which services are configured
        services = list(proxy._config.services.keys())
        logger.info(
            "API key proxy started (services=%s, anomaly_detection=%s)",
            ", ".join(services),
            proxy._config.enable_anomaly_detection,
        )

        return True

    except ImportError as e:
        logger.debug("API key proxy not available: %s", e)
    except (OSError, RuntimeError, ValueError) as e:
        logger.warning("Failed to start API key proxy: %s", e)

    return False


def validate_required_secrets() -> dict:
    """Validate that required secrets are available at startup.

    In production, checks that critical secrets come from AWS Secrets Manager
    rather than environment variables. In development, just checks they exist.

    Returns:
        Dict with validation results: {valid: bool, errors: list, warnings: list}
    """
    import os

    errors: list[str] = []
    warnings: list[str] = []
    env = os.environ.get("ARAGORA_ENV", "development")
    is_production = env in ("production", "staging")

    # Required secrets for any environment (at least one AI provider)
    ai_keys = [
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
    ]
    has_any_ai_key = any(os.environ.get(k) for k in ai_keys)
    if not has_any_ai_key:
        errors.append(
            "No AI provider API key found (need at least one of: " + ", ".join(ai_keys) + ")"
        )

    # Production-only requirements
    if is_production:
        critical_secrets = [
            "ARAGORA_JWT_SECRET",
            "ARAGORA_ENCRYPTION_KEY",
        ]
        for secret in critical_secrets:
            if not os.environ.get(secret):
                errors.append(f"Missing critical production secret: {secret}")

        # Check if Secrets Manager is configured
        use_sm = os.environ.get("ARAGORA_USE_SECRETS_MANAGER", "").lower() == "true"
        if not use_sm:
            warnings.append(
                "ARAGORA_USE_SECRETS_MANAGER not enabled. "
                "Production deployments should use AWS Secrets Manager."
            )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


async def init_decision_router() -> bool:
    """Initialize the DecisionRouter with platform response handlers.

    Registers response handlers for all supported platforms so the router
    can deliver debate results back to the originating channel.

    Returns:
        True if initialization succeeded
    """
    try:
        from aragora.core.decision import get_decision_router
        from aragora.server.debate_origin import route_debate_result

        router = get_decision_router()

        # Register platform response handlers
        # These handlers use route_debate_result to deliver results
        # back to the originating channel

        async def telegram_handler(result, channel):
            from aragora.server.debate_origin import get_debate_origin

            origin = get_debate_origin(result.request_id)
            if origin and origin.platform == "telegram":
                await route_debate_result(result.request_id, result.to_dict())

        async def slack_handler(result, channel):
            from aragora.server.debate_origin import get_debate_origin

            origin = get_debate_origin(result.request_id)
            if origin and origin.platform == "slack":
                await route_debate_result(result.request_id, result.to_dict())

        async def discord_handler(result, channel):
            from aragora.server.debate_origin import get_debate_origin

            origin = get_debate_origin(result.request_id)
            if origin and origin.platform == "discord":
                await route_debate_result(result.request_id, result.to_dict())

        async def whatsapp_handler(result, channel):
            from aragora.server.debate_origin import get_debate_origin

            origin = get_debate_origin(result.request_id)
            if origin and origin.platform == "whatsapp":
                await route_debate_result(result.request_id, result.to_dict())

        async def teams_handler(result, channel):
            from aragora.server.debate_origin import get_debate_origin

            origin = get_debate_origin(result.request_id)
            if origin and origin.platform == "teams":
                await route_debate_result(result.request_id, result.to_dict())

        async def email_handler(result, channel):
            from aragora.server.debate_origin import get_debate_origin

            origin = get_debate_origin(result.request_id)
            if origin and origin.platform == "email":
                await route_debate_result(result.request_id, result.to_dict())

        async def google_chat_handler(result, channel):
            from aragora.server.debate_origin import get_debate_origin

            origin = get_debate_origin(result.request_id)
            if origin and origin.platform in ("google_chat", "gchat"):
                await route_debate_result(result.request_id, result.to_dict())

        # Register all handlers
        router.register_response_handler("telegram", telegram_handler)
        router.register_response_handler("slack", slack_handler)
        router.register_response_handler("discord", discord_handler)
        router.register_response_handler("whatsapp", whatsapp_handler)
        router.register_response_handler("teams", teams_handler)
        router.register_response_handler("email", email_handler)
        router.register_response_handler("google_chat", google_chat_handler)
        router.register_response_handler("gchat", google_chat_handler)

        logger.info("DecisionRouter initialized with 8 platform response handlers")
        return True

    except (ImportError, RuntimeError, AttributeError) as e:
        logger.warning("Failed to initialize DecisionRouter: %s", e)
        return False


async def init_mfa_drift_monitor() -> bool:
    """Initialize the MFA policy drift monitor for admin-role users.

    Starts a periodic background scanner that detects admin accounts
    without MFA enabled (policy drift) and emits structured log alerts.

    SOC 2 Control: CC5-01 - Enforce MFA for administrative access.

    The monitor only starts when auth is configured (i.e. a user store
    is available).  If the notification service is available, violation
    callbacks are wired; otherwise structured logging is used as the
    default alerting mechanism.

    Failure to start the monitor does NOT prevent server startup
    (graceful degradation).

    Environment Variables:
        ARAGORA_MFA_DRIFT_ENABLED: Set to "true" to enable
            (default: "true" in production, "false" otherwise)
        ARAGORA_MFA_DRIFT_INTERVAL: Seconds between scans (default: 3600)
        ARAGORA_MFA_DRIFT_THRESHOLD: Minimum compliance rate 0.0-1.0
            (default: 1.0 = 100%% of admins must have MFA)

    Returns:
        True if the monitor was started, False otherwise
    """
    import os

    env = os.environ.get("ARAGORA_ENV", "development")
    default_enabled = "true" if env == "production" else "false"
    enabled = os.environ.get("ARAGORA_MFA_DRIFT_ENABLED", default_enabled).lower() in (
        "true",
        "1",
        "yes",
    )

    if not enabled:
        logger.debug("MFA drift monitor disabled (set ARAGORA_MFA_DRIFT_ENABLED=true to enable)")
        return False

    try:
        from aragora.auth.mfa_drift_monitor import init_mfa_drift_monitor as _init_monitor
        from aragora.storage.user_store.singleton import get_user_store

        user_store = get_user_store()
        if user_store is None:
            logger.debug("MFA drift monitor not started: no user store available")
            return False

        # Read configuration from environment
        interval = int(os.environ.get("ARAGORA_MFA_DRIFT_INTERVAL", "3600"))
        threshold = float(os.environ.get("ARAGORA_MFA_DRIFT_THRESHOLD", "1.0"))

        # Wire notification callback if the notification service is available
        on_violation = None
        try:
            from aragora.notifications.service import get_notification_service

            notif_svc = get_notification_service()
            if notif_svc is not None:

                def _notify_violation(report) -> None:
                    """Forward MFA drift violation to the notification service."""
                    try:
                        notif_svc.send(
                            channel="security",
                            subject="MFA policy drift detected",
                            body=report.summary,
                            metadata=report.to_dict(),
                        )
                    except (RuntimeError, OSError, ValueError, AttributeError) as exc:
                        logger.warning("Failed to send MFA drift notification: %s", exc)

                on_violation = _notify_violation
        except ImportError:
            logger.debug("Notification service not available, using log-only MFA drift alerts")

        # Initialize and start the monitor
        monitor = _init_monitor(
            user_store=user_store,
            alert_threshold=threshold,
            on_violation=on_violation,
        )
        await monitor.start(interval_seconds=interval)

        logger.info(
            "MFA drift monitor started (interval=%ds, threshold=%.0f%%)",
            interval,
            threshold * 100,
        )
        return True

    except ImportError as e:
        logger.debug("MFA drift monitor not available: %s", e)
    except (OSError, RuntimeError, ValueError) as e:
        logger.warning("Failed to start MFA drift monitor: %s", e)

    return False


async def init_aws_rotation_monitor() -> bool:
    """Initialize the AWS Secrets Manager rotation monitor.

    Starts a background task that:
    1. Checks if any secrets are within their rotation window
    2. Hot-reloads secrets from AWS Secrets Manager when rotation completes
    3. Hydrates environment variables with refreshed values

    The monitor integrates with the existing SecretManager cache and
    provides status via /api/v1/admin/security/rotation-status.

    Environment Variables:
        ARAGORA_ROTATION_MONITOR_ENABLED: Set to "true" to enable
            (default: auto-enabled when ARAGORA_USE_SECRETS_MANAGER=true)
        ARAGORA_ROTATION_CHECK_INTERVAL: Seconds between checks (default: 300)

    Returns:
        True if the monitor was started, False otherwise
    """
    import os

    # Auto-enable when AWS Secrets Manager is configured
    use_aws = os.environ.get("ARAGORA_USE_SECRETS_MANAGER", "").lower() in (
        "true",
        "1",
        "yes",
    )
    explicit = os.environ.get("ARAGORA_ROTATION_MONITOR_ENABLED", "").lower()

    if explicit == "false":
        logger.debug("AWS rotation monitor explicitly disabled")
        return False

    if not use_aws and explicit != "true":
        logger.debug(
            "AWS rotation monitor not started (AWS Secrets Manager not configured). "
            "Set ARAGORA_ROTATION_MONITOR_ENABLED=true to force."
        )
        return False

    try:
        from aragora.security.aws_key_rotation import init_rotation_on_startup

        monitor = await init_rotation_on_startup()

        if monitor is not None:
            logger.info(
                "AWS rotation monitor started (check every %ss, tracking %d secrets)",
                monitor._check_interval,
                len(monitor.rotator.get_all_rotation_statuses()),
            )
            return True

        logger.debug("AWS rotation monitor returned None (not needed)")
        return False

    except ImportError as e:
        logger.debug("AWS rotation monitor not available: %s", e)
    except (OSError, RuntimeError, ValueError) as e:
        logger.warning("Failed to start AWS rotation monitor: %s", e)

    return False
