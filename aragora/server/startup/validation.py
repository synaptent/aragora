"""
Server startup validation functions.

This module handles configuration validation, connectivity checks,
and production requirements verification.
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Sentinel messages returned by connectivity validators when no backend is
# configured and the connectivity probe is therefore skipped. These callers
# treat the result as a non-failure (bool ``True``) for startup-gating
# purposes, but the skip MUST NOT be reported to humans/CI as a validated
# connection. Use :func:`is_connectivity_skipped` to distinguish the cases.
REDIS_SKIP_MESSAGE = "Redis not configured (skipping connectivity check)"
DATABASE_SKIP_MESSAGE = "PostgreSQL not configured (skipping connectivity check)"
_CONNECTIVITY_SKIP_MESSAGES = frozenset({REDIS_SKIP_MESSAGE, DATABASE_SKIP_MESSAGE})


def is_connectivity_skipped(message: str) -> bool:
    """Return True when a connectivity validator skipped (no backend configured).

    The Redis/PostgreSQL validators return ``(True, message)`` for the
    unconfigured case so that optional backends do not fail startup gating.
    A ``True`` success bool therefore does NOT imply a connection was made.
    Callers that surface results to humans or CI (e.g. ``validate-env``) use
    this predicate to avoid reporting a skipped check as ``connected``.
    """
    return message in _CONNECTIVITY_SKIP_MESSAGES


def _get_config_value(name: str) -> str | None:
    """Get configuration value from environment or secrets manager."""
    import os

    # First check environment
    value = os.environ.get(name)
    if value:
        return value

    # Try secrets manager as fallback
    try:
        from aragora.config.secrets import get_secret

        return get_secret(name)
    except ImportError:
        return None
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, Exception):
        # Catches SecretNotFoundError and other secrets manager errors
        return None


def _openrouter_fallback_configured() -> bool:
    """Return True when OpenRouter fallback is available for direct API agents."""
    if not _get_config_value("OPENROUTER_API_KEY"):
        return False

    try:
        from aragora.agents.fallback import get_default_fallback_enabled

        return get_default_fallback_enabled()
    except (ImportError, AttributeError, RuntimeError, OSError, ValueError):
        return True


def _redis_backend_configured() -> bool:
    """Return True when any supported Redis runtime configuration is present."""
    import os

    if os.environ.get("REDIS_URL") or os.environ.get("ARAGORA_REDIS_URL"):
        return True
    if os.environ.get("ARAGORA_REDIS_SENTINEL_HOSTS"):
        return True
    if os.environ.get("ARAGORA_REDIS_CLUSTER_NODES"):
        return True
    return os.environ.get("ARAGORA_REDIS_MODE", "").lower() in {"sentinel", "cluster"}


def check_connector_dependencies() -> list[str]:
    """Check if connector dependencies are available.

    SECURITY: Connectors fail-closed when dependencies are missing, but this
    function provides early warnings at startup to help operators identify
    misconfiguration before runtime failures occur.

    Returns:
        List of warnings for missing connector dependencies
    """
    import os

    warnings = []

    # Discord webhook verification requires PyNaCl
    if os.environ.get("DISCORD_PUBLIC_KEY") or os.environ.get("DISCORD_WEBHOOK_URL"):
        try:
            import nacl.signing  # noqa: F401
        except ImportError:
            warnings.append(
                "Discord connector configured but PyNaCl not installed. "
                "Webhook signature verification will fail-closed. "
                "Install with: pip install pynacl"
            )

    # Teams/Google Chat webhook verification requires PyJWT
    teams_configured = os.environ.get("TEAMS_TENANT_ID") or os.environ.get("TEAMS_WEBHOOK_URL")
    gchat_configured = os.environ.get("GOOGLE_CHAT_PROJECT") or os.environ.get(
        "GOOGLE_CHAT_WEBHOOK_URL"
    )
    if teams_configured or gchat_configured:
        try:
            import jwt  # noqa: F401
        except ImportError:
            connectors = []
            if teams_configured:
                connectors.append("Teams")
            if gchat_configured:
                connectors.append("Google Chat")
            warnings.append(
                f"{'/'.join(connectors)} connector configured but PyJWT not installed. "
                "Webhook signature verification will fail-closed. "
                "Install with: pip install pyjwt"
            )

    # Slack webhook verification requires signing secret
    if os.environ.get("SLACK_WEBHOOK_URL") and not os.environ.get("SLACK_SIGNING_SECRET"):
        warnings.append(
            "Slack webhook configured but SLACK_SIGNING_SECRET not set. "
            "Webhook signature verification will fail-closed unless "
            "ARAGORA_WEBHOOK_ALLOW_UNVERIFIED=1 is set (not recommended for production)."
        )

    # Slack OAuth configuration validation
    slack_oauth_configured = os.environ.get("SLACK_CLIENT_ID") or os.environ.get(
        "SLACK_CLIENT_SECRET"
    )
    if slack_oauth_configured:
        slack_oauth_issues = []

        if not os.environ.get("SLACK_CLIENT_ID"):
            slack_oauth_issues.append("SLACK_CLIENT_ID")
        if not os.environ.get("SLACK_CLIENT_SECRET"):
            slack_oauth_issues.append("SLACK_CLIENT_SECRET")

        if slack_oauth_issues:
            warnings.append(
                f"Slack OAuth partially configured - missing: {', '.join(slack_oauth_issues)}. "
                "OAuth installation flow will fail without both variables set."
            )

        # Validate SLACK_REDIRECT_URI in production
        is_production = os.environ.get("ARAGORA_ENV", "development") == "production"
        redirect_uri = os.environ.get("SLACK_REDIRECT_URI", "")

        if is_production and not redirect_uri:
            warnings.append(
                "SLACK_REDIRECT_URI not set in production. "
                "Slack OAuth flow may fail or redirect to unexpected URLs."
            )
        elif redirect_uri and not redirect_uri.startswith("https://"):
            if is_production:
                warnings.append(
                    "SLACK_REDIRECT_URI must use HTTPS in production. "
                    f"Current value: {redirect_uri}"
                )

        # Encryption key is recommended for token storage
        if not os.environ.get("ARAGORA_ENCRYPTION_KEY") and is_production:
            warnings.append(
                "ARAGORA_ENCRYPTION_KEY not set - Slack OAuth tokens will be stored "
                "UNENCRYPTED. This is a security risk in production."
            )

    return warnings


def check_agent_credentials(default_agents: str | None = None) -> list[str]:
    """Check for missing API keys required by default agents.

    This validates that environment variables or AWS Secrets Manager provide
    the credentials needed to instantiate the configured default agents.
    """
    from aragora.config.settings import get_settings

    warnings: list[str] = []
    agents_str = default_agents or get_settings().agent.default_agents
    agent_names = [a.strip() for a in agents_str.split(",") if a.strip()]

    # Agents backed by OpenRouter (single key)
    openrouter_agents = {
        "deepseek",
        "kimi",
        "mistral",
        "qwen",
        "qwen-max",
    }
    if any(agent in openrouter_agents for agent in agent_names):
        if not _get_config_value("OPENROUTER_API_KEY"):
            warnings.append(
                "OPENROUTER_API_KEY missing for OpenRouter-backed agents "
                f"({', '.join(sorted(openrouter_agents & set(agent_names)))}). "
                "Set via env or AWS Secrets Manager (ARAGORA_USE_SECRETS_MANAGER=1)."
            )

    fallback_available = _openrouter_fallback_configured()

    # Direct API providers
    if "openai-api" in agent_names and not (
        _get_config_value("OPENAI_API_KEY") or fallback_available
    ):
        warnings.append("OPENAI_API_KEY missing for openai-api agent (env or Secrets Manager).")
    if "anthropic-api" in agent_names and not (
        _get_config_value("ANTHROPIC_API_KEY") or fallback_available
    ):
        warnings.append(
            "ANTHROPIC_API_KEY missing for anthropic-api agent (env or Secrets Manager)."
        )
    if "gemini" in agent_names and not (
        _get_config_value("GEMINI_API_KEY")
        or _get_config_value("GOOGLE_API_KEY")
        or fallback_available
    ):
        warnings.append(
            "GEMINI_API_KEY or GOOGLE_API_KEY missing for gemini agent (env or Secrets Manager)."
        )
    if "grok" in agent_names and not (
        _get_config_value("XAI_API_KEY") or _get_config_value("GROK_API_KEY") or fallback_available
    ):
        warnings.append(
            "XAI_API_KEY or GROK_API_KEY missing for grok agent (env or Secrets Manager)."
        )
    if "mistral-api" in agent_names and not (
        _get_config_value("MISTRAL_API_KEY") or fallback_available
    ):
        warnings.append("MISTRAL_API_KEY missing for mistral-api agent (env or Secrets Manager).")

    return warnings


def check_production_requirements() -> list[str]:
    """Check if production requirements are met.

    SECURITY: This function performs fail-fast validation of production
    configuration to prevent runtime failures and security misconfigurations.

    Environment Variables:
        ARAGORA_ENV: Set to "production" to enable production checks
        ARAGORA_MULTI_INSTANCE: Set to "true" to require Redis for HA
        ARAGORA_REQUIRE_DATABASE: Set to "true" to require PostgreSQL

    Returns:
        List of missing requirements (empty if all met)
    """
    import os

    from aragora.control_plane.leader import is_distributed_state_required

    missing = []
    warnings = []
    env = os.environ.get("ARAGORA_ENV", "development")
    is_production = env == "production"
    distributed_state_required = is_distributed_state_required()
    require_database = os.environ.get("ARAGORA_REQUIRE_DATABASE", "").lower() in (
        "true",
        "1",
        "yes",
    )

    # Strict secrets mode (production/staging by default) needs a managed custody
    # backend. ARAGORA_ENV alone no longer enables AWS Secrets Manager, so a
    # deployment that relied on that would otherwise start without its secrets.
    from aragora.config.secrets import is_strict_mode, managed_custody_problem

    custody_problem = managed_custody_problem() if is_strict_mode() else None
    if custody_problem:
        missing.append(
            "Strict secrets mode is on (ARAGORA_ENV=production/staging or "
            f"ARAGORA_SECRETS_STRICT=true) but {custody_problem}. Mount protected "
            "secret files and set ARAGORA_SECRETS_DIR to an absolute, trusted "
            "directory, or enable AWS Secrets Manager with "
            "ARAGORA_USE_SECRETS_MANAGER=true (ARAGORA_ENV no longer enables it), or "
            "set ARAGORA_SECRETS_STRICT=false (not recommended)"
        )

    if is_production:
        # =====================================================================
        # HARD REQUIREMENTS (fail startup)
        # =====================================================================

        # Encryption key is required for production
        if not _get_config_value("ARAGORA_ENCRYPTION_KEY"):
            missing.append(
                "ARAGORA_ENCRYPTION_KEY required in production "
                "(32-byte hex string for AES-256 encryption)"
            )

        # Distributed state mode requires Redis
        if distributed_state_required:
            if not _redis_backend_configured():
                missing.append(
                    "Redis configuration (REDIS_URL/ARAGORA_REDIS_URL or Sentinel/Cluster settings) "
                    "required for distributed state (multi-instance or production). Redis is "
                    "needed for: session store, control-plane leader election, debate origins, "
                    "and distributed caching. "
                    "Set ARAGORA_SINGLE_INSTANCE=true if running single-node."
                )

        # Database requirement (optional flag for strict deployments)
        if require_database:
            if not os.environ.get("DATABASE_URL"):
                missing.append(
                    "DATABASE_URL required when ARAGORA_REQUIRE_DATABASE=true. "
                    "PostgreSQL is needed for: governance store, audit logs, "
                    "and enterprise connector sync."
                )

        # =====================================================================
        # SOFT REQUIREMENTS (warnings)
        # =====================================================================

        # Redis recommended for durable state
        if not distributed_state_required and not _redis_backend_configured():
            warnings.append(
                "Redis configuration not set - using in-memory state for sessions, debate "
                "origins, and control plane. Data will be lost on restart. "
                "Set ARAGORA_MULTI_INSTANCE=true to make Redis mandatory."
            )

        # PostgreSQL recommended for governance store
        if not require_database and not os.environ.get("DATABASE_URL"):
            warnings.append(
                "DATABASE_URL not set - using SQLite for governance store. "
                "PostgreSQL recommended for production. "
                "Set ARAGORA_REQUIRE_DATABASE=true to make it mandatory."
            )

        # JWT secret should be set for auth
        if not _get_config_value("JWT_SECRET") and not _get_config_value("ARAGORA_JWT_SECRET"):
            warnings.append(
                "JWT_SECRET not set - using derived key from encryption key. "
                "Consider setting JWT_SECRET for independent key rotation."
            )

    # Check connector dependencies (warnings, not errors)
    connector_warnings = check_connector_dependencies()
    warnings.extend(connector_warnings)

    # Check agent API keys for default agents (warnings, not errors)
    agent_warnings = check_agent_credentials()
    warnings.extend(agent_warnings)

    # Check insecure JWT mode (SECURITY: should never be in production)
    allow_insecure_jwt = os.environ.get("ARAGORA_ALLOW_INSECURE_JWT", "").lower() in (
        "true",
        "1",
        "yes",
    )
    if allow_insecure_jwt:
        if is_production:
            warnings.append(
                "ARAGORA_ALLOW_INSECURE_JWT is set in production! "
                "This flag is IGNORED in production but indicates a "
                "configuration error. Remove it from your production environment."
            )
        else:
            logger.warning(
                "[SECURITY] ARAGORA_ALLOW_INSECURE_JWT=true - JWTs will be decoded "
                "without signature verification. This is a security risk."
            )

    # Check demo mode status
    demo_mode = os.environ.get("ARAGORA_DEMO_MODE", "").lower() in ("true", "1", "yes")
    if demo_mode:
        if is_production:
            warnings.append(
                "ARAGORA_DEMO_MODE is enabled in production! "
                "Mock data will be returned for some endpoints. "
                "This should only be used for demos, not real deployments."
            )
        else:
            logger.info(
                "[DEMO MODE] ARAGORA_DEMO_MODE=true - Mock data will be returned "
                "when backend services are unavailable."
            )

    # Log all warnings
    for warning in warnings:
        logger.warning("[PRODUCTION CONFIG] %s", warning)

    # Log summary
    if is_production:
        if missing:
            logger.error(
                "[PRODUCTION CONFIG] %s critical requirement(s) missing. Server startup will fail.",
                len(missing),
            )
        elif warnings:
            logger.warning(
                "[PRODUCTION CONFIG] %s recommendation(s) not met. Server will start but may have reduced durability.",
                len(warnings),
            )
        else:
            logger.info("[PRODUCTION CONFIG] All production requirements met.")

    return missing


async def validate_redis_connectivity(timeout_seconds: float = 5.0) -> tuple[bool, str]:
    """Test Redis connectivity with a PING command.

    This function validates that Redis is actually reachable when required,
    not just that REDIS_URL is configured. This catches common issues like:
    - Network connectivity problems
    - Authentication failures
    - Redis server not running

    Args:
        timeout_seconds: Connection timeout in seconds

    Returns:
        Tuple of (success: bool, message: str)
    """
    import os

    sentinel_hosts = os.environ.get("ARAGORA_REDIS_SENTINEL_HOSTS", "").strip()
    cluster_nodes = os.environ.get("ARAGORA_REDIS_CLUSTER_NODES", "").strip()
    redis_mode = os.environ.get("ARAGORA_REDIS_MODE", "").strip().lower()

    if sentinel_hosts or cluster_nodes or redis_mode in {"sentinel", "cluster"}:
        try:
            from aragora.storage.redis_ha import RedisHAConfig, check_async_redis_health

            health = await check_async_redis_health(RedisHAConfig.from_env())
            if health.get("healthy"):
                info = health.get("info", {})
                redis_version = info.get("redis_version", "unknown")
                mode = health.get("mode", redis_mode or "redis")
                return True, f"Redis connected via {mode} (version {redis_version})"
            error = health.get("error") or "Redis health check failed"
            return False, f"Redis connection failed: {error}"
        except ImportError:
            return False, "redis package not installed - run: pip install redis"

    redis_url = os.environ.get("REDIS_URL") or os.environ.get("ARAGORA_REDIS_URL")
    if not redis_url:
        return True, REDIS_SKIP_MESSAGE

    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(
            redis_url,
            socket_connect_timeout=timeout_seconds,
            socket_timeout=timeout_seconds,
        )
        try:
            result = await asyncio.wait_for(client.ping(), timeout=timeout_seconds)
            if result:
                # Check if we can get server info (validates auth)
                info = await asyncio.wait_for(client.info("server"), timeout=timeout_seconds)
                redis_version = info.get("redis_version", "unknown")
                return True, f"Redis connected (version {redis_version})"
            return False, "Redis PING failed"
        finally:
            # redis-py async clients expose aclose(); the bundled stubs are stale.
            await client.aclose()  # type: ignore[attr-defined]
    except ImportError:
        return False, "redis package not installed - run: pip install redis"
    except asyncio.TimeoutError:
        return False, f"Redis connection timed out after {timeout_seconds}s"
    except (ConnectionError, OSError, ValueError, RuntimeError) as e:
        return False, f"Redis connection failed: {e}"
    except Exception as e:  # noqa: BLE001 - redis.exceptions.ConnectionError doesn't inherit builtins.ConnectionError
        # Catch redis.exceptions.ConnectionError and other client-specific errors
        # (redis.exceptions.ConnectionError is NOT a subclass of builtin ConnectionError)
        if "ConnectionError" in type(e).__name__ or "redis" in type(e).__module__:
            return False, f"Redis connection failed: {e}"
        raise


async def validate_database_connectivity(timeout_seconds: float = 5.0) -> tuple[bool, str]:
    """Test PostgreSQL connectivity with a simple query.

    This function validates that PostgreSQL is actually reachable when required,
    not just that DATABASE_URL is configured. This catches common issues like:
    - Network connectivity problems
    - Authentication failures
    - Database server not running
    - Database doesn't exist

    Args:
        timeout_seconds: Connection timeout in seconds

    Returns:
        Tuple of (success: bool, message: str)
    """
    import os

    database_url = os.environ.get("DATABASE_URL") or os.environ.get("ARAGORA_POSTGRES_DSN")
    if not database_url:
        return True, DATABASE_SKIP_MESSAGE

    try:
        import asyncpg

        try:
            conn = await asyncio.wait_for(
                asyncpg.connect(database_url, timeout=timeout_seconds),
                timeout=timeout_seconds,
            )
            try:
                # Run a simple query to validate connection
                version = await conn.fetchval("SELECT version()")
                # Extract just the version string (e.g., "PostgreSQL 15.4")
                version_short = version.split(",")[0] if version else "unknown"
                return True, f"PostgreSQL connected ({version_short})"
            finally:
                await conn.close()
        except asyncio.TimeoutError:
            return False, f"PostgreSQL connection timed out after {timeout_seconds}s"
    except ImportError:
        return False, "asyncpg package not installed - run: pip install asyncpg"
    except (ConnectionError, OSError, ValueError, RuntimeError) as e:
        return False, f"PostgreSQL connection failed: {e}"


async def validate_database_connectivity_with_retry(
    timeout_seconds: float = 5.0,
    max_retries: int = 3,
    initial_backoff: float = 1.0,
    max_backoff: float = 30.0,
    backoff_multiplier: float = 2.0,
) -> tuple[bool, str]:
    """Test PostgreSQL connectivity with exponential backoff retry.

    This is the recommended function for production startup. It provides
    resilience against transient database connectivity issues during startup,
    such as when the database is still initializing or network is settling.

    Args:
        timeout_seconds: Connection timeout per attempt
        max_retries: Maximum number of retry attempts (0 = no retries)
        initial_backoff: Initial backoff delay in seconds
        max_backoff: Maximum backoff delay in seconds
        backoff_multiplier: Multiplier for exponential backoff

    Returns:
        Tuple of (success: bool, message: str)

    Example:
        # At startup, use retry version for resilience
        ok, msg = await validate_database_connectivity_with_retry(
            max_retries=5,
            initial_backoff=2.0,
        )
        if not ok:
            raise StartupError(f"Database unavailable: {msg}")
    """
    last_error = ""
    backoff = initial_backoff

    for attempt in range(max_retries + 1):
        success, message = await validate_database_connectivity(timeout_seconds)

        if success:
            if attempt > 0:
                logger.info(
                    "[DB STARTUP] PostgreSQL connectivity validated after %s retries", attempt
                )
            return True, message

        last_error = message

        if attempt < max_retries:
            logger.warning(
                f"[DB STARTUP] Attempt {attempt + 1}/{max_retries + 1} failed: {message}. "
                f"Retrying in {backoff:.1f}s..."
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * backoff_multiplier, max_backoff)

    logger.error(
        "[DB STARTUP] PostgreSQL connectivity failed after %s attempts: %s",
        max_retries + 1,
        last_error,
    )
    return False, f"Failed after {max_retries + 1} attempts: {last_error}"


async def validate_redis_connectivity_with_retry(
    timeout_seconds: float = 5.0,
    max_retries: int = 3,
    initial_backoff: float = 1.0,
    max_backoff: float = 30.0,
    backoff_multiplier: float = 2.0,
) -> tuple[bool, str]:
    """Test Redis connectivity with exponential backoff retry.

    This is the recommended function for production startup. It provides
    resilience against transient Redis connectivity issues during startup.

    Args:
        timeout_seconds: Connection timeout per attempt
        max_retries: Maximum number of retry attempts (0 = no retries)
        initial_backoff: Initial backoff delay in seconds
        max_backoff: Maximum backoff delay in seconds
        backoff_multiplier: Multiplier for exponential backoff

    Returns:
        Tuple of (success: bool, message: str)
    """
    last_error = ""
    backoff = initial_backoff

    for attempt in range(max_retries + 1):
        success, message = await validate_redis_connectivity(timeout_seconds)

        if success:
            if attempt > 0:
                logger.info(
                    "[REDIS STARTUP] Redis connectivity validated after %s retries", attempt
                )
            return True, message

        last_error = message

        if attempt < max_retries:
            logger.warning(
                f"[REDIS STARTUP] Attempt {attempt + 1}/{max_retries + 1} failed: {message}. "
                f"Retrying in {backoff:.1f}s..."
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * backoff_multiplier, max_backoff)

    logger.error(
        "[REDIS STARTUP] Redis connectivity failed after %s attempts: %s",
        max_retries + 1,
        last_error,
    )
    return False, f"Failed after {max_retries + 1} attempts: {last_error}"


async def validate_backend_connectivity(
    require_redis: bool = False,
    require_database: bool = False,
    timeout_seconds: float = 5.0,
    enable_retries: bool | None = None,
    max_retries: int = 3,
    initial_backoff: float = 1.0,
) -> dict[str, Any]:
    """Validate connectivity to all configured backends.

    This function should be called during startup after environment validation
    to ensure that configured backends are actually reachable.

    Args:
        require_redis: If True, fail if Redis is not reachable
        require_database: If True, fail if PostgreSQL is not reachable
        timeout_seconds: Timeout for each connectivity test
        enable_retries: Enable retry with exponential backoff. If None, uses
                       ARAGORA_STARTUP_RETRY_ENABLED env var (default: True in production)
        max_retries: Maximum retry attempts when retries enabled
        initial_backoff: Initial backoff delay in seconds

    Environment Variables:
        ARAGORA_STARTUP_RETRY_ENABLED: Set to "false" to disable retries (default: "true")
        ARAGORA_STARTUP_MAX_RETRIES: Override max_retries (default: 3)
        ARAGORA_STARTUP_INITIAL_BACKOFF: Override initial_backoff (default: 1.0)

    Returns:
        Dictionary with connectivity status:
        {
            "valid": True/False,
            "redis": {"connected": bool, "message": str},
            "database": {"connected": bool, "message": str},
            "errors": [str, ...],
            "retries_enabled": bool
        }
    """
    import os

    # Skip connectivity checks in offline mode
    from aragora.utils.env import is_offline_mode

    if is_offline_mode():
        logger.info("[BACKEND CHECK] Offline mode — skipping connectivity checks")
        return {
            "valid": True,
            "redis": {"connected": False, "message": "Skipped (offline mode)"},
            "database": {"connected": False, "message": "Skipped (offline mode)"},
            "errors": [],
            "retries_enabled": False,
        }

    errors: list[str] = []

    # Determine if retries should be enabled
    if enable_retries is None:
        enable_retries = os.environ.get("ARAGORA_STARTUP_RETRY_ENABLED", "true").lower() in (
            "true",
            "1",
            "yes",
        )

    # Allow env var overrides for retry configuration
    max_retries = int(os.environ.get("ARAGORA_STARTUP_MAX_RETRIES", str(max_retries)))
    initial_backoff = float(os.environ.get("ARAGORA_STARTUP_INITIAL_BACKOFF", str(initial_backoff)))

    # Test Redis connectivity (with or without retry)
    if enable_retries and require_redis:
        redis_ok, redis_msg = await validate_redis_connectivity_with_retry(
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            initial_backoff=initial_backoff,
        )
    else:
        redis_ok, redis_msg = await validate_redis_connectivity(timeout_seconds)

    if not redis_ok and require_redis:
        errors.append(f"Redis connectivity required but failed: {redis_msg}")

    # Test database connectivity (with or without retry)
    if enable_retries and require_database:
        db_ok, db_msg = await validate_database_connectivity_with_retry(
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            initial_backoff=initial_backoff,
        )
    else:
        db_ok, db_msg = await validate_database_connectivity(timeout_seconds)

    if not db_ok and require_database:
        errors.append(f"PostgreSQL connectivity required but failed: {db_msg}")

    # Log results
    if redis_ok and "connected" in redis_msg.lower():
        logger.info("[BACKEND CHECK] %s", redis_msg)
    elif not redis_ok:
        logger.warning("[BACKEND CHECK] Redis: %s", redis_msg)

    if db_ok and "connected" in db_msg.lower():
        logger.info("[BACKEND CHECK] %s", db_msg)
    elif not db_ok:
        logger.warning("[BACKEND CHECK] PostgreSQL: %s", db_msg)

    return {
        "valid": len(errors) == 0,
        "redis": {"connected": redis_ok, "message": redis_msg},
        "database": {"connected": db_ok, "message": db_msg},
        "errors": errors,
        "retries_enabled": enable_retries,
    }


def validate_storage_backend() -> dict[str, Any]:
    """Validate storage backend configuration for production.

    This function ensures that the correct storage backend is being used
    in production environments. SQLite is not suitable for multi-instance
    deployments as each server would have its own isolated database.

    Returns:
        Dictionary with validation results:
        {
            "valid": True/False,
            "backend": "supabase" | "postgres" | "sqlite",
            "is_production": True/False,
            "warnings": [str, ...],
            "errors": [str, ...]
        }
    """
    import os

    from aragora.storage.factory import get_storage_backend, StorageBackend

    errors: list[str] = []
    warnings: list[str] = []

    env = os.environ.get("ARAGORA_ENV", "development")
    is_production = env == "production"
    backend = get_storage_backend()
    allow_sqlite = os.environ.get("ARAGORA_ALLOW_SQLITE_FALLBACK", "").lower() in (
        "true",
        "1",
    )

    if is_production and backend == StorageBackend.SQLITE:
        if allow_sqlite:
            warnings.append(
                "SQLite backend used in production with ARAGORA_ALLOW_SQLITE_FALLBACK=true. "
                "This is not recommended for multi-instance deployments. "
                "Users created on one server will not be visible on other servers."
            )
        else:
            errors.append(
                "Production environment requires distributed storage (Supabase or PostgreSQL). "
                "SQLite is not suitable for multi-instance deployments. "
                "Configure SUPABASE_URL + SUPABASE_DB_PASSWORD or ARAGORA_POSTGRES_DSN, "
                "or set ARAGORA_ALLOW_SQLITE_FALLBACK=true to override (not recommended)."
            )

    # Log results
    backend_name = backend.value
    if backend == StorageBackend.SUPABASE:
        logger.info("[STORAGE BACKEND] Using Supabase PostgreSQL (recommended)")
    elif backend == StorageBackend.POSTGRES:
        logger.info("[STORAGE BACKEND] Using self-hosted PostgreSQL")
    else:
        if is_production:
            logger.warning("[STORAGE BACKEND] Using SQLite in production (not recommended)")
        else:
            logger.info("[STORAGE BACKEND] Using SQLite (development mode)")

    for warning in warnings:
        logger.warning("[STORAGE BACKEND] %s", warning)
    for error in errors:
        logger.error("[STORAGE BACKEND] %s", error)

    return {
        "valid": len(errors) == 0,
        "backend": backend_name,
        "is_production": is_production,
        "warnings": warnings,
        "errors": errors,
    }
