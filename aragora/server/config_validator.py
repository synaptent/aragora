"""
Configuration validator for Aragora server startup.

Validates environment variables and configuration at startup to provide
clear error messages for misconfigurations instead of runtime failures.

Usage:
    from aragora.server.config_validator import ConfigValidator

    # Run validation at startup
    errors = ConfigValidator.validate()
    if errors:
        for error in errors:
            print(f"Configuration error: {error}")
        sys.exit(1)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import cast

from aragora.config.secrets import SecretNotFoundError, SecretSourceError, get_secret

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of configuration validation."""

    is_valid: bool
    errors: list[str]
    warnings: list[str]

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0


class ConfigValidator:
    """
    Validates configuration at server startup.

    Checks environment variables, validates their values, and ensures
    the server can start successfully.
    """

    # Environment variables that are required in production mode
    PRODUCTION_REQUIRED = ["ARAGORA_API_TOKEN", "DATABASE_URL"]

    # Insecure development-only environment variables that must NOT be set in production
    # Setting these in production creates security vulnerabilities
    INSECURE_DEV_ONLY_VARS = {
        "ARAGORA_ALLOW_DEV_AUTH_FALLBACK": (
            "Allows JWT tokens without signature verification. "
            "This bypasses authentication security entirely."
        ),
        "ARAGORA_ALLOW_INSECURE_PASSWORDS": (
            "Allows SHA-256 password hashing instead of bcrypt. "
            "SHA-256 is computationally fast, making password cracking easier."
        ),
        "ARAGORA_ALLOW_UNSAFE_SAML": (
            "Allows SAML authentication without signature validation. "
            "This allows attackers to forge SAML responses and bypass authentication."
        ),
        "ARAGORA_ALLOW_UNSAFE_SAML_CONFIRMED": (
            "Confirmation for unsafe SAML mode. "
            "Only relevant when ARAGORA_ALLOW_UNSAFE_SAML is also set."
        ),
    }

    # SAML configuration variables - presence indicates SAML is configured
    SAML_CONFIG_VARS = ["SAML_IDP_ENTITY_ID", "SAML_IDP_SSO_URL", "SAML_ENTITY_ID"]

    # At least one of these LLM API keys should be present
    LLM_API_KEYS = [
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "MISTRAL_API_KEY",
        "GEMINI_API_KEY",
        "XAI_API_KEY",
    ]

    # Security-sensitive variables with minimum requirements
    SECRET_REQUIREMENTS = {
        "JWT_SECRET": {"min_length": 32, "description": "JWT signing secret"},
        "ARAGORA_API_TOKEN": {"min_length": 16, "description": "API authentication token"},
    }

    # Variables that should be validated as URLs
    URL_VARS = ["SUPABASE_URL", "REDIS_URL", "ARAGORA_BASE_URL"]

    # Variables that should be validated as integers
    INTEGER_VARS = [
        "ARAGORA_RATE_LIMIT",
        "ARAGORA_IP_RATE_LIMIT",
        "ARAGORA_PORT",
        "ARAGORA_TOKEN_TTL",
        "ARAGORA_INSTANCE_COUNT",
    ]

    @classmethod
    def validate(cls, strict: bool = False) -> list[str]:
        """
        Validate configuration and return list of errors.

        Args:
            strict: If True, treat warnings as errors

        Returns:
            List of error messages (empty if valid)
        """
        result = cls.validate_all()

        if strict:
            return result.errors + result.warnings
        return result.errors

    @classmethod
    def validate_all(cls) -> ValidationResult:
        """
        Run all validation checks.

        Returns:
            ValidationResult with errors and warnings
        """
        errors: list[str] = []
        warnings: list[str] = []
        secret_values: dict[str, str | None] = {}
        secret_source_errors: set[str] = set()

        def _secret_value(name: str) -> str | None:
            if name not in secret_values:
                try:
                    secret_values[name] = get_secret(name)
                except SecretSourceError:
                    secret_values[name] = None
                    secret_source_errors.add(name)
                except (SecretNotFoundError, OSError, RuntimeError, ValueError):
                    secret_values[name] = None
            return secret_values[name]

        # Check production mode requirements
        env_mode = (
            os.getenv("ARAGORA_ENV") or os.getenv("ARAGORA_ENVIRONMENT") or "development"
        ).lower()
        is_production = env_mode in ("production", "prod", "staging", "stage")

        if is_production:
            for var in cls.PRODUCTION_REQUIRED:
                if not _secret_value(var):
                    if var in secret_source_errors:
                        errors.append(f"Invalid managed custody configuration for {var}")
                    else:
                        errors.append(
                            f"Missing required configuration in production/staging: {var}"
                        )

            # SECURITY: Check for insecure development-only variables in production
            for var, description in cls.INSECURE_DEV_ONLY_VARS.items():
                value = os.getenv(var, "").lower()
                if value in ("1", "true", "yes"):
                    errors.append(
                        f"SECURITY VIOLATION: {var} is set in production. "
                        f"{description} Remove this variable before deploying to production."
                    )

        # Check LLM API keys
        has_llm_key = any(_secret_value(key) for key in cls.LLM_API_KEYS)
        if not has_llm_key:
            msg = f"No LLM API key configured. Set at least one of: {', '.join(cls.LLM_API_KEYS)}"
            if is_production:
                errors.append(msg)
            else:
                warnings.append(msg)

        # SECURITY: Warn if production env vars are set but ARAGORA_ENV is not production
        # This catches accidental deployments with development settings
        aragora_env = env_mode
        if not is_production:
            has_production_vars = any(
                os.getenv(var) for var in ["ARAGORA_API_TOKEN", "DATABASE_URL", "REDIS_URL"]
            )
            if has_production_vars:
                warnings.append(
                    f"Production environment variables detected but ARAGORA_ENV='{aragora_env}'. "
                    "Set ARAGORA_ENV=production to enable production security checks, or "
                    "remove production variables if this is a development environment."
                )

        # Check secret requirements
        for var, req in cls.SECRET_REQUIREMENTS.items():
            secret_value = _secret_value(var)
            if secret_value:
                min_len = cast(int, req["min_length"])
                if len(secret_value) < min_len:
                    errors.append(
                        f"{var} ({req['description']}) must be at least "
                        f"{min_len} characters, got {len(secret_value)}"
                    )

        # Validate URL formats
        for var in cls.URL_VARS:
            url_value = _secret_value(var)
            if url_value:
                if var == "REDIS_URL":
                    if not url_value.startswith("redis://"):
                        errors.append(f"{var} must be a valid Redis URL (redis://...)")
                elif not (url_value.startswith("http://") or url_value.startswith("https://")):
                    errors.append(f"{var} must be a valid URL (http:// or https://)")

        # Validate integer formats
        for var in cls.INTEGER_VARS:
            integer_value = os.getenv(var)
            if integer_value:
                try:
                    int(integer_value)
                except ValueError:
                    errors.append(f"{var} must be an integer, got: {integer_value}")

        # Check database configuration in production
        if is_production:
            db_url = _secret_value("DATABASE_URL")
            if db_url:
                # Ensure PostgreSQL is used in production (not SQLite)
                if "sqlite" in db_url.lower():
                    errors.append(
                        "SQLite is not supported in production. "
                        "Set DATABASE_URL to a PostgreSQL connection string "
                        "(e.g., postgresql://user:pass@host:5432/dbname)"
                    )
                elif not db_url.startswith(("postgresql://", "postgres://")):
                    errors.append(
                        "DATABASE_URL must be a PostgreSQL connection string in production "
                        "(starting with postgresql:// or postgres://)"
                    )

                # Validate PostgreSQL pool configuration
                try:
                    from aragora.storage.resilience import validate_postgres_pool_config

                    pool_valid, pool_errors = validate_postgres_pool_config()
                    errors.extend(pool_errors)
                except ImportError:
                    pass  # Resilience module not available

        # Check CORS configuration
        allowed_origins = os.getenv("ARAGORA_ALLOWED_ORIGINS", "")
        if is_production and not allowed_origins:
            warnings.append(
                "ARAGORA_ALLOWED_ORIGINS not set in production. "
                "CORS may block requests from web clients."
            )

        # SECURITY: Enforce HTTPS origins in production
        if is_production and allowed_origins:
            origins_list = [o.strip() for o in allowed_origins.split(",") if o.strip()]
            insecure_origins = [
                o
                for o in origins_list
                if o.startswith("http://") and "localhost" not in o and "127.0.0.1" not in o
            ]
            if insecure_origins:
                errors.append(
                    f"SECURITY: Non-HTTPS origins in production: {', '.join(insecure_origins)}. "
                    "All production origins must use HTTPS. Update ARAGORA_ALLOWED_ORIGINS to use https:// URLs."
                )

        # Check rate limiting configuration
        rate_limit = os.getenv("ARAGORA_RATE_LIMIT")
        if rate_limit:
            try:
                if int(rate_limit) < 1:
                    errors.append("ARAGORA_RATE_LIMIT must be positive")
            except ValueError:
                pass  # Already checked in INTEGER_VARS

        # Check Redis configuration for production multi-instance deployments
        # In-memory rate limiting and session storage don't work across instances
        if is_production:
            redis_url = _secret_value("REDIS_URL")
            instance_count = os.getenv("ARAGORA_INSTANCE_COUNT", "1")

            # Check if running multiple instances without Redis
            try:
                instances = int(instance_count)
            except ValueError:
                instances = 1

            if instances > 1 and not redis_url:
                errors.append(
                    "REDIS_URL is required when running multiple instances (ARAGORA_INSTANCE_COUNT > 1). "
                    "In-memory rate limiting and session storage don't work across instances. "
                    "Set REDIS_URL to a Redis connection string (e.g., redis://localhost:6379/0)"
                )
            elif not redis_url:
                # Single instance but still production - warn about stateful data
                warnings.append(
                    "REDIS_URL not set in production. Rate limiting and session data "
                    "will be stored in-memory and lost on restart. Consider configuring Redis "
                    "for persistent state (set REDIS_URL=redis://host:port/db)"
                )

        # Check SAML library availability if SAML is configured
        saml_ok, saml_error = cls.check_saml_library_availability()
        if not saml_ok and saml_error:
            errors.append(saml_error)

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    @classmethod
    def check_saml_library_availability(cls) -> tuple[bool, str | None]:
        """
        Check if python3-saml library is available when SAML is configured.

        SAML authentication requires the python3-saml library for proper
        signature validation. Without it, SAML responses cannot be securely
        validated and attackers could forge user identities.

        Pre-flight checks (H-1 security fix):
        - Attempts to import python3-saml during server startup
        - If import fails AND environment is production/staging, logs a WARNING
        - If ARAGORA_ALLOW_UNSAFE_SAML is set in production/staging, logs CRITICAL

        Returns:
            (success, error_message) tuple. If success is False, error_message
            contains the error description.
        """
        env = os.getenv("ARAGORA_ENV", "").lower()
        is_prod_or_staging = env in ("production", "prod", "staging", "stage")

        # SECURITY: Pre-flight check for unsafe SAML override in production/staging
        allow_unsafe = os.getenv("ARAGORA_ALLOW_UNSAFE_SAML", "").lower() in (
            "1",
            "true",
            "yes",
        )
        if is_prod_or_staging and allow_unsafe:
            logger.critical(
                "SECURITY: ARAGORA_ALLOW_UNSAFE_SAML is set in %s environment. "
                "This disables SAML signature validation, allowing attackers to "
                "forge authentication assertions. Remove this variable immediately.",
                env,
            )

        # Pre-flight: attempt python3-saml import
        saml_lib_available = False
        try:
            from onelogin.saml2.auth import OneLogin_Saml2_Auth  # noqa: F401

            saml_lib_available = True
        except ImportError:
            if is_prod_or_staging:
                logger.warning(
                    "SAML pre-flight: python3-saml library is not available in %s. "
                    "SAML authentication will not have signature validation. "
                    "Install with: pip install python3-saml",
                    env,
                )

        # Check if SAML appears to be configured
        saml_configured = any(os.getenv(var) for var in cls.SAML_CONFIG_VARS)

        if not saml_configured:
            return True, None  # SAML not configured, not an error

        # SAML is configured - require library in production/staging
        if is_prod_or_staging and not saml_lib_available:
            return False, (
                "SAML is configured but python3-saml library is not installed. "
                "Install with: pip install python3-saml"
            )

        # In development, allow without the library (will fail at runtime with clear error)
        return True, None

    @classmethod
    def validate_and_log(cls, strict: bool = False) -> bool:
        """
        Validate configuration and log errors/warnings.

        Args:
            strict: If True, treat warnings as errors

        Returns:
            True if configuration is valid
        """
        result = cls.validate_all()

        for warning in result.warnings:
            logger.warning("Configuration warning: %s", warning)

        for error in result.errors:
            logger.error("Configuration error: %s", error)

        if strict and result.has_warnings:
            return False

        return result.is_valid

    @classmethod
    def check_database_connectivity(cls) -> tuple[bool, str | None]:
        """
        Check if database is accessible (if configured).

        Returns:
            (success, error_message) tuple
        """
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_ANON_KEY")

        if not supabase_url or not supabase_key:
            return True, None  # Not configured, not an error

        try:
            from aragora.persistence.supabase_client import SupabaseClient

            client = SupabaseClient()
            if not client.is_configured:
                return False, "Supabase client not properly configured"

            # Try a simple query to verify connectivity
            # This is a lightweight check
            return True, None
        except ImportError:
            return True, None  # Module not available, not an error
        except (ConnectionError, TimeoutError, OSError) as e:
            return False, f"Database connectivity check failed: {e}"

    @classmethod
    def check_postgresql_connectivity(
        cls,
        timeout_seconds: float = 5.0,
        skip_connectivity_test: bool = False,
    ) -> tuple[bool, str | None]:
        """
        Check if PostgreSQL is accessible (if configured).

        Performs an actual connection test to verify database connectivity,
        not just configuration format validation.

        Args:
            timeout_seconds: Maximum time to wait for connection.
            skip_connectivity_test: If True, only validate config format (for testing).

        Returns:
            (success, error_message) tuple
        """
        database_url = os.getenv("DATABASE_URL")

        if not database_url:
            return True, None  # Not configured, not an error

        if not database_url.startswith(("postgresql://", "postgres://")):
            return True, None  # Not PostgreSQL

        try:
            import asyncpg
        except ImportError:
            return False, "asyncpg package required for PostgreSQL support"

        if skip_connectivity_test:
            return True, None

        # Actually test the connection
        import asyncio

        async def _test_connection() -> tuple[bool, str | None]:
            conn = None
            try:
                conn = await asyncio.wait_for(
                    asyncpg.connect(database_url),
                    timeout=timeout_seconds,
                )
                # Verify connection works with a simple query
                result = await conn.fetchval("SELECT 1")
                if result != 1:
                    return False, "Database query returned unexpected result"
                return True, None
            except asyncio.TimeoutError:
                return False, f"Database connection timeout after {timeout_seconds}s"
            except asyncpg.PostgresError as e:
                return False, f"Database connection failed: {e}"
            except (ConnectionError, TimeoutError, OSError) as e:
                return False, f"Database connectivity check failed: {e}"
            finally:
                if conn:
                    await conn.close()

        # Run async test in event loop
        try:
            # Check if there's already a running loop
            try:
                asyncio.get_running_loop()
                # Already in async context - can't run sync
                # Return success but warn
                logger.warning(
                    "PostgreSQL connectivity test skipped: already in async context. "
                    "Connection will be verified at first use."
                )
                return True, None
            except RuntimeError:
                # No running loop - create one
                return asyncio.run(_test_connection())
        except (RuntimeError, OSError) as e:
            return False, f"Failed to run connectivity test: {e}"

    @classmethod
    def check_redis_connectivity(cls) -> tuple[bool, str | None]:
        """
        Check if Redis is accessible (if configured).

        Returns:
            (success, error_message) tuple
        """
        redis_url = os.getenv("REDIS_URL")

        if not redis_url:
            return True, None  # Not configured, not an error

        try:
            import redis

            client = redis.from_url(redis_url, socket_connect_timeout=5)
            client.ping()
            return True, None
        except ImportError:
            return True, None  # Redis not installed, not an error
        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            return False, f"Redis connectivity check failed: {e}"
        except Exception as e:  # noqa: BLE001 - redis.exceptions.ConnectionError doesn't inherit builtins.ConnectionError
            if "redis" in type(e).__module__:
                return False, f"Redis connectivity check failed: {e}"
            raise

    @classmethod
    def check_alembic_migrations(cls) -> tuple[bool, str | None]:
        """
        Check if Alembic database migrations are up to date.

        Verifies that the database schema matches the latest migrations
        to prevent serving traffic with an outdated schema.

        Returns:
            (success, error_message) tuple. Returns (True, None) if migrations
            are up to date or Alembic is not configured. Returns (False, message)
            if migrations are pending.
        """
        database_url = os.getenv("DATABASE_URL")

        if not database_url:
            return True, None  # No database configured

        if not database_url.startswith(("postgresql://", "postgres://")):
            return True, None  # Not PostgreSQL, skip migration check

        try:
            from alembic.config import Config
            from alembic.runtime.migration import MigrationContext
            from alembic.script import ScriptDirectory
            from sqlalchemy import create_engine
        except ImportError:
            # Alembic not installed - skip check
            return True, None

        try:
            # Find alembic.ini - check common locations
            alembic_ini_paths = [
                "alembic.ini",
                "migrations/alembic.ini",
                os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini"),
            ]

            alembic_ini = None
            for path in alembic_ini_paths:
                if os.path.exists(path):
                    alembic_ini = path
                    break

            if not alembic_ini:
                # No alembic.ini found - migrations not configured
                return True, None

            config = Config(alembic_ini)
            config.set_main_option("sqlalchemy.url", database_url)

            # Get script directory for head revisions
            script = ScriptDirectory.from_config(config)
            heads = set(script.get_heads())

            if not heads:
                # No migrations defined
                return True, None

            # Get current database revision
            engine = create_engine(database_url)
            with engine.connect() as connection:
                context = MigrationContext.configure(connection)
                current_revisions = set(context.get_current_heads())

            engine.dispose()

            # Check if current matches heads
            if current_revisions != heads:
                missing = heads - current_revisions
                if missing:
                    return False, (
                        f"Database schema is out of date. "
                        f"Pending migrations: {', '.join(missing)}. "
                        f"Run 'alembic upgrade head' before starting the server."
                    )

            logger.info("Alembic migrations are up to date")
            return True, None

        except (ImportError, OSError, RuntimeError, ValueError) as e:
            # Log but don't fail startup for migration check errors
            logger.warning("Could not verify Alembic migrations: %s", e)
            return True, None

    @classmethod
    async def check_postgresql_connectivity_async(
        cls,
        timeout_seconds: float = 5.0,
    ) -> tuple[bool, str | None]:
        """
        Async version of PostgreSQL connectivity check.

        Use this in async contexts like server startup.

        Args:
            timeout_seconds: Maximum time to wait for connection.

        Returns:
            (success, error_message) tuple
        """
        import asyncio

        database_url = os.getenv("DATABASE_URL")

        if not database_url:
            return True, None  # Not configured, not an error

        if not database_url.startswith(("postgresql://", "postgres://")):
            return True, None  # Not PostgreSQL

        try:
            import asyncpg
        except ImportError:
            return False, "asyncpg package required for PostgreSQL support"

        conn = None
        try:
            conn = await asyncio.wait_for(
                asyncpg.connect(database_url),
                timeout=timeout_seconds,
            )
            # Verify connection works with a simple query
            result = await conn.fetchval("SELECT 1")
            if result != 1:
                return False, "Database query returned unexpected result"
            logger.info("PostgreSQL connectivity verified")
            return True, None
        except asyncio.TimeoutError:
            return False, f"Database connection timeout after {timeout_seconds}s"
        except (ConnectionError, TimeoutError, OSError) as e:
            return False, f"Database connectivity check failed: {e}"
        finally:
            if conn:
                await conn.close()

    @classmethod
    async def validate_connectivity_async(
        cls,
        check_postgresql: bool = True,
        check_redis: bool = True,
        check_migrations: bool = True,
    ) -> ValidationResult:
        """
        Validate database and cache connectivity (async version).

        Use this during async server startup to verify all backends are reachable.

        Args:
            check_postgresql: Whether to check PostgreSQL connectivity.
            check_redis: Whether to check Redis connectivity.
            check_migrations: Whether to check Alembic migrations are up to date.

        Returns:
            ValidationResult with any connectivity errors.
        """
        errors: list[str] = []
        warnings: list[str] = []
        is_production = os.getenv("ARAGORA_ENV", "development").lower() == "production"

        if check_postgresql:
            success, error = await cls.check_postgresql_connectivity_async()
            if not success and error:
                if is_production:
                    errors.append(f"PostgreSQL: {error}")
                else:
                    warnings.append(f"PostgreSQL: {error}")

        if check_redis:
            success, error = cls.check_redis_connectivity()
            if not success and error:
                if is_production:
                    errors.append(f"Redis: {error}")
                else:
                    warnings.append(f"Redis: {error}")

        if check_migrations:
            success, error = cls.check_alembic_migrations()
            if not success and error:
                if is_production:
                    errors.append(f"Migrations: {error}")
                else:
                    warnings.append(f"Migrations: {error}")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    @classmethod
    def get_config_summary(cls) -> dict:
        """
        Get a summary of current configuration for debugging.

        Sensitive values are masked.
        """

        def mask_value(value: str) -> str:
            if not value:
                return "(not set)"
            if len(value) <= 8:
                return "*" * len(value)
            return value[:4] + "*" * (len(value) - 8) + value[-4:]

        db_url = os.getenv("DATABASE_URL", "")
        db_backend = "sqlite"
        if db_url.startswith(("postgresql://", "postgres://")):
            db_backend = "postgresql"
        elif db_url:
            db_backend = "unknown"

        return {
            "environment": os.getenv("ARAGORA_ENV", "development"),
            "api_token_set": bool(os.getenv("ARAGORA_API_TOKEN")),
            "jwt_secret_set": bool(os.getenv("JWT_SECRET")),
            "jwt_secret_length": len(os.getenv("JWT_SECRET", "")),
            "llm_keys": {key: bool(os.getenv(key)) for key in cls.LLM_API_KEYS},
            "database_backend": db_backend,
            "database_url_set": bool(db_url),
            "supabase_configured": bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY")),
            "redis_configured": bool(os.getenv("REDIS_URL")),
            "rate_limit": os.getenv("ARAGORA_RATE_LIMIT", "60"),
            "allowed_origins": bool(os.getenv("ARAGORA_ALLOWED_ORIGINS")),
        }


def validate_startup_config(strict: bool = False, exit_on_error: bool = True) -> bool:
    """
    Convenience function to validate configuration at startup.

    Args:
        strict: If True, treat warnings as errors
        exit_on_error: If True, exit the process on validation failure

    Returns:
        True if configuration is valid
    """
    is_valid = ConfigValidator.validate_and_log(strict=strict)

    if not is_valid and exit_on_error:
        import sys

        logger.critical("Server startup aborted due to configuration errors")
        sys.exit(1)

    return is_valid


async def validate_startup_config_async(
    strict: bool = False,
    check_connectivity: bool = True,
) -> ValidationResult:
    """
    Async convenience function to validate configuration and connectivity at startup.

    Args:
        strict: If True, treat warnings as errors
        check_connectivity: If True, verify database/cache connectivity

    Returns:
        ValidationResult with all validation errors and warnings
    """
    # Run standard config validation
    result = ConfigValidator.validate_all()

    # Optionally check connectivity
    if check_connectivity:
        connectivity_result = await ConfigValidator.validate_connectivity_async()
        result.errors.extend(connectivity_result.errors)
        result.warnings.extend(connectivity_result.warnings)
        result.is_valid = len(result.errors) == 0

    # Log results
    for warning in result.warnings:
        logger.warning("Configuration warning: %s", warning)

    for error in result.errors:
        logger.error("Configuration error: %s", error)

    return result


__all__ = [
    "ConfigValidator",
    "ValidationResult",
    "validate_startup_config",
    "validate_startup_config_async",
]
