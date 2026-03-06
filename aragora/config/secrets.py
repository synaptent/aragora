"""
AWS Secrets Manager integration for Aragora.

This module provides secure secret management with multiple fallback strategies:
1. AWS Secrets Manager (production)
2. Environment variables (local development)
3. Default values (for non-sensitive config)

Security Features:
- Strict mode: Critical secrets MUST come from Secrets Manager in production
- Audit logging for SOC 2 compliance
- Automatic cache expiration
- Thread-safe secret access

Usage:
    from aragora.config.secrets import get_secret, SecretManager

    # Get individual secrets
    jwt_secret = get_secret("JWT_SECRET_KEY")
    stripe_key = get_secret("STRIPE_SECRET_KEY")

    # Or use the manager for batch loading
    manager = SecretManager()
    secrets = manager.get_secrets(["JWT_SECRET_KEY", "STRIPE_SECRET_KEY"])

Production Mode:
    In production (ARAGORA_ENV=production), critical secrets will NOT fall back
    to environment variables. This prevents accidental use of .env files in
    production and enforces proper secret management.

    Set ARAGORA_SECRETS_STRICT=false to disable strict mode (not recommended).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, cast

logger = logging.getLogger(__name__)

# Import botocore exceptions for proper error handling
# These are optional - if not installed, we use Exception as fallback
_BOTOCORE_AVAILABLE = False
try:
    from botocore.exceptions import BotoCoreError, ClientError

    _BOTOCORE_AVAILABLE = True
except ImportError:
    # Placeholder exceptions when botocore is not installed.
    # We create these as module-level classes to avoid mypy redefinition errors.
    pass


# Define fallback exception classes only when botocore is not available
if not _BOTOCORE_AVAILABLE:

    class ClientError(Exception):  # type: ignore[no-redef]  # noqa: N818 - Matches botocore naming
        """Fallback ClientError when botocore is not installed."""

        response: dict[str, dict[str, str]]

        def __init__(self, *args: object, **kwargs: Any) -> None:
            super().__init__(*args)
            response_value = kwargs.get("response", {})
            self.response = cast(dict[str, dict[str, str]], response_value)

    class BotoCoreError(Exception):  # type: ignore[no-redef]
        """Fallback BotoCoreError when botocore is not installed."""

        pass


# Secret names that should be loaded from Secrets Manager
MANAGED_SECRETS = frozenset(
    {
        # Authentication
        "JWT_SECRET_KEY",
        "JWT_REFRESH_SECRET",
        "ARAGORA_JWT_SECRET",
        # Encryption
        "ARAGORA_ENCRYPTION_KEY",
        # Audit signing
        "ARAGORA_AUDIT_SIGNING_KEY",
        # OAuth
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GITHUB_OAUTH_CLIENT_ID",
        "GITHUB_OAUTH_CLIENT_SECRET",
        # Gmail OAuth (for inbox integration)
        "GMAIL_CLIENT_ID",
        "GMAIL_CLIENT_SECRET",
        # Stripe billing
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_PRICE_STARTER",
        "STRIPE_PRICE_PROFESSIONAL",
        "STRIPE_PRICE_ENTERPRISE",
        # Database (Supabase PostgreSQL)
        "DATABASE_URL",
        "ARAGORA_POSTGRES_DSN",
        "SUPABASE_URL",
        "SUPABASE_KEY",
        "SUPABASE_DB_PASSWORD",
        "SUPABASE_POSTGRES_DSN",
        "SUPABASE_SERVICE_ROLE_KEY",
        # Redis
        "REDIS_URL",
        "REDIS_PASSWORD",
        # API Keys (sensitive)
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "XAI_API_KEY",
        "OPENROUTER_API_KEY",
        "MISTRAL_API_KEY",
        "DEEPSEEK_API_KEY",
        "SUPERMEMORY_API_KEY",
        "KIMI_API_KEY",
        "ELEVENLABS_API_KEY",
        "FAL_API_KEY",
        "AZURE_CLIENT_SECRET",
        "SUPABASE_PROJECT_ID",
        # Monitoring
        "SENTRY_DSN",
        # Deployment (Vercel)
        "VERCEL_TOKEN",
        "VERCEL_ORG_ID",
        "VERCEL_PROJECT_ID",
        # Grok (xAI) - alternate key name
        "GROK_API_KEY",
    }
)

# CRITICAL SECRETS - These MUST NOT fall back to environment variables in production
# These are high-value secrets where env var fallback could indicate a security issue
CRITICAL_SECRETS = frozenset(
    {
        # Authentication - Compromise allows session forging
        "JWT_SECRET_KEY",
        "JWT_REFRESH_SECRET",
        "ARAGORA_JWT_SECRET",
        # Encryption - Compromise allows data decryption
        "ARAGORA_ENCRYPTION_KEY",
        "ARAGORA_AUDIT_SIGNING_KEY",
        # Database - Full data access
        "DATABASE_URL",
        "ARAGORA_POSTGRES_DSN",
        "SUPABASE_DB_PASSWORD",
        "SUPABASE_POSTGRES_DSN",
        "SUPABASE_SERVICE_ROLE_KEY",
        # Payment - Financial data access
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
    }
)


class SecretNotFoundError(Exception):
    """Raised when a critical secret is not found in Secrets Manager."""

    def __init__(self, name: str, message: str | None = None):
        self.name = name
        if message:
            super().__init__(message)
        else:
            super().__init__(
                f"Critical secret '{name}' not found in AWS Secrets Manager. "
                f"In production, critical secrets must be stored in Secrets Manager, "
                f"not environment variables. Configure AWS Secrets Manager or set "
                f"ARAGORA_SECRETS_STRICT=false to disable strict mode (not recommended)."
            )


def is_strict_mode() -> bool:
    """
    Check if strict secrets mode is enabled.

    Strict mode is enabled by default in production/staging environments.
    In strict mode, critical secrets MUST come from AWS Secrets Manager,
    not environment variables.

    Returns:
        True if strict mode is enabled
    """
    # Check explicit override first
    explicit = os.environ.get("ARAGORA_SECRETS_STRICT", "").lower()
    if explicit in ("false", "0", "no"):
        return False
    if explicit in ("true", "1", "yes"):
        return True

    # Default: strict in production/staging
    env = os.environ.get("ARAGORA_ENV", "").lower()
    return env in ("production", "prod", "staging", "stage")


def is_critical_secret(name: str) -> bool:
    """Check if a secret is classified as critical."""
    return name in CRITICAL_SECRETS


@dataclass
class SecretsConfig:
    """Configuration for secrets management."""

    # AWS Secrets Manager settings
    aws_region: str = "us-east-1"
    aws_regions: list[str] = field(default_factory=list)
    secret_name: str = "aragora/production"  # noqa: S105 -- AWS Secrets Manager path
    use_aws: bool = False

    # Cache settings
    cache_ttl_seconds: int = 300

    @classmethod
    def from_env(cls) -> SecretsConfig:
        """Load config from environment.

        AWS Secrets Manager is enabled by default. It gracefully falls back
        to environment variables when AWS credentials or boto3 are
        unavailable, so there is no harm in leaving it on.

        Set ARAGORA_USE_SECRETS_MANAGER=false to explicitly disable.
        """
        use_flag = os.environ.get("ARAGORA_USE_SECRETS_MANAGER", "")
        if use_flag:
            use_aws = use_flag.lower() in ("true", "1", "yes")
        else:
            # Default: always try AWS Secrets Manager.  _load_from_aws()
            # handles missing boto3, credentials, or secret gracefully by
            # returning an empty dict, at which point get() falls through
            # to environment variables.
            use_aws = True

        primary_region = (
            os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
        )
        raw_regions = os.environ.get("ARAGORA_SECRET_REGIONS", "")
        explicit_regions = [r.strip() for r in raw_regions.split(",") if r.strip()]
        if explicit_regions:
            regions = []
            for region in [primary_region, *explicit_regions]:
                if region and region not in regions:
                    regions.append(region)
        else:
            regions = [primary_region]
            if primary_region != "us-east-2":
                regions.append("us-east-2")
            if primary_region != "us-east-1":
                regions.append("us-east-1")
        return cls(
            aws_region=primary_region,
            aws_regions=regions,
            secret_name=os.environ.get("ARAGORA_SECRET_NAME", "aragora/production"),
            use_aws=use_aws,
        )


class SecretManager:
    """
    Manages secrets from multiple sources with fallback.

    Priority order:
    1. AWS Secrets Manager (if enabled)
    2. Environment variables
    3. Default values (for non-sensitive config)

    Features:
    - Automatic cache expiration based on TTL
    - Audit logging for secret access (SOC 2 compliance)
    - Thread-safe secret access
    """

    def __init__(self, config: SecretsConfig | None = None):
        self.config = config or SecretsConfig.from_env()
        self._aws_clients: dict[str, Any] = {}
        self._cached_secrets: dict[str, str] = {}
        self._cache_timestamp: float = 0.0
        self._initialized = False
        self._lock = threading.Lock()
        self._access_log: list[dict[str, Any]] = []
        self._max_access_log_size = 1000
        self._warned_env_secrets: set[str] = set()

    def _is_cache_expired(self) -> bool:
        """Check if the secret cache has expired."""
        import time

        if self._cache_timestamp == 0.0:
            return True
        elapsed = time.time() - self._cache_timestamp
        return elapsed > self.config.cache_ttl_seconds

    def _log_access(self, secret_name: str, source: str, success: bool) -> None:
        """Log secret access for audit purposes (SOC 2 compliance)."""
        import time

        entry = {
            "timestamp": time.time(),
            "secret_name": secret_name,
            "source": source,  # "aws", "env", "default"
            "success": success,
        }
        with self._lock:
            self._access_log.append(entry)
            # Trim log if too large
            if len(self._access_log) > self._max_access_log_size:
                self._access_log = self._access_log[-self._max_access_log_size // 2 :]

    def get_access_log(self) -> list[dict[str, Any]]:
        """Get the access log for audit purposes."""
        with self._lock:
            return list(self._access_log)

    def _get_aws_client(self, region: str) -> Any:
        """Lazily initialize AWS Secrets Manager client for a region."""
        if region in self._aws_clients:
            return self._aws_clients[region]

        try:
            import boto3

            client = boto3.client("secretsmanager", region_name=region)
            self._aws_clients[region] = client
            return client
        except ImportError:
            logger.debug("boto3 not installed, AWS Secrets Manager unavailable")
            return None
        except (BotoCoreError, ClientError) as e:
            # Catch boto3/botocore specific exceptions
            logger.warning(
                "Failed to initialize AWS client (%s): %s: %s", region, type(e).__name__, e
            )
            return None
        except (OSError, RuntimeError, ValueError) as e:
            # Catch remaining non-boto exceptions (e.g., config errors, network)
            logger.warning(
                "Failed to initialize AWS client (%s): %s: %s", region, type(e).__name__, e
            )
            return None

    def _load_from_aws(self) -> dict[str, str]:
        """Load secrets from AWS Secrets Manager."""
        if not self.config.use_aws:
            return {}

        regions = self.config.aws_regions or [self.config.aws_region]
        if not regions:
            return {}

        last_error: Exception | None = None
        for region in regions:
            client = self._get_aws_client(region)
            if client is None:
                continue
            try:
                response = client.get_secret_value(SecretId=self.config.secret_name)
                secret_string = response.get("SecretString", "{}")
                secrets: dict[str, str] = json.loads(secret_string)
                logger.info(
                    "Loaded %d secrets from AWS Secrets Manager (region=%s)",
                    len(secrets),
                    region,
                )
                return secrets
            except json.JSONDecodeError as e:
                logger.error("Failed to parse secrets JSON from AWS (region=%s): %s", region, e)
                return {}
            except (ClientError, BotoCoreError) as e:
                # Handle boto3/botocore specific exceptions
                last_error = e
                if hasattr(e, "response"):
                    error_code = e.response.get("Error", {}).get("Code", "")
                    if error_code == "ResourceNotFoundException":
                        logger.warning(
                            "Secret '%s' not found in AWS (region=%s)",
                            self.config.secret_name,
                            region,
                        )
                        continue
                    if error_code == "AccessDeniedException":
                        logger.warning("Access denied to AWS Secrets Manager (region=%s)", region)
                        continue
                    logger.error(
                        "AWS Secrets Manager error (region=%s): %s: %s", region, error_code, e
                    )
                else:
                    logger.error(
                        "AWS/botocore error (region=%s): %s: %s", region, type(e).__name__, e
                    )
                continue
            except (OSError, RuntimeError, ValueError, KeyError) as e:
                # Catch remaining non-boto exceptions (e.g., config errors, network)
                last_error = e
                logger.error(
                    "Unexpected error loading secrets (region=%s): %s: %s",
                    region,
                    type(e).__name__,
                    e,
                )
                continue

        if last_error:
            logger.warning("Failed to load secrets from AWS Secrets Manager in all regions")
        return {}

    def _initialize(self, force_refresh: bool = False) -> None:
        """Initialize the secret manager (load from AWS if enabled).

        Args:
            force_refresh: Force reload from AWS even if cache is valid
        """
        import time

        with self._lock:
            # First initialization
            if not self._initialized:
                logger.debug(
                    "Initializing SecretManager: use_aws=%s, secret_name=%s, regions=%s",
                    self.config.use_aws,
                    self.config.secret_name,
                    self.config.aws_regions,
                )
                if self.config.use_aws:
                    self._cached_secrets = self._load_from_aws()
                    self._cache_timestamp = time.time()
                    if self._cached_secrets:
                        logger.info(
                            "Secrets cache initialized with %d secrets, TTL: %ds",
                            len(self._cached_secrets),
                            self.config.cache_ttl_seconds,
                        )
                    else:
                        logger.warning(
                            "Secrets cache initialized but EMPTY - AWS loading may have failed"
                        )
                else:
                    logger.debug("AWS Secrets Manager disabled, using environment variables only")
                self._initialized = True
                return

            # Already initialized - check if refresh needed (only for AWS)
            if not self.config.use_aws:
                return  # No AWS, no refresh needed

            needs_refresh = force_refresh or self._is_cache_expired()
            if not needs_refresh:
                return

            self._cached_secrets = self._load_from_aws()
            self._cache_timestamp = time.time()
            logger.debug("Secrets cache refreshed, TTL: %ss", self.config.cache_ttl_seconds)

    def refresh(self) -> None:
        """Force refresh secrets from AWS (for manual rotation)."""
        self._initialize(force_refresh=True)
        logger.info("Secrets manually refreshed")

    def get(
        self,
        name: str,
        default: str | None = None,
        strict: bool | None = None,
    ) -> str | None:
        """
        Get a secret value.

        Args:
            name: Secret name (e.g., "JWT_SECRET_KEY")
            default: Default value if not found
            strict: Override strict mode for this call (None = use global setting)

        Returns:
            Secret value or default

        Raises:
            SecretNotFoundError: If strict mode is enabled for a critical secret
                and it's not found in AWS Secrets Manager
        """
        self._initialize()

        # Determine if strict mode applies
        use_strict = strict if strict is not None else is_strict_mode()
        is_critical = is_critical_secret(name)

        # 1. Check AWS cache first
        if name in self._cached_secrets:
            self._log_access(name, "aws", True)
            return self._cached_secrets[name]

        # Debug: Log cache miss for managed secrets
        if name in MANAGED_SECRETS:
            cached_keys = list(self._cached_secrets.keys())[:10]  # First 10 for brevity
            logger.debug(
                "Secret '%s' not in AWS cache. Cache has %d secrets. Sample keys: %s",
                name,
                len(self._cached_secrets),
                cached_keys,
            )

        # 2. Check environment variable
        env_value = os.environ.get(name)

        # In strict mode, critical secrets MUST NOT come from env vars
        if use_strict and is_critical:
            if env_value is not None:
                # Log warning - env var exists but shouldn't be used
                logger.warning(
                    "SECURITY: Critical secret '%s' found in environment variable "
                    "but strict mode is enabled. This secret should be in AWS "
                    "Secrets Manager. Ignoring env var value.",
                    name,
                )
                self._log_access(name, "env_blocked", False)
            # Secret not in AWS - raise error
            self._log_access(name, "not_found_strict", False)
            raise SecretNotFoundError(name)

        # Non-strict mode or non-critical secret - allow env fallback
        if env_value is not None:
            if is_critical and name not in self._warned_env_secrets:
                self._warned_env_secrets.add(name)
                logger.warning(
                    "SECURITY: Critical secret '%s' loaded from environment variable. "
                    "Consider migrating to AWS Secrets Manager for production use.",
                    name,
                )
            self._log_access(name, "env", True)
            return env_value

        # 3. Return default
        if default is not None:
            self._log_access(name, "default", True)
        else:
            self._log_access(name, "not_found", False)
        return default

    def get_required(self, name: str) -> str:
        """
        Get a required secret value.

        Args:
            name: Secret name

        Returns:
            Secret value

        Raises:
            ValueError: If secret is not found
        """
        value = self.get(name)
        if value is None:
            raise ValueError(f"Required secret '{name}' not found")
        return value

    def get_secrets(self, names: list[str]) -> dict[str, str | None]:
        """
        Get multiple secrets at once.

        Args:
            names: List of secret names

        Returns:
            Dictionary of secret name -> value (or None if not found)
        """
        return {name: self.get(name) for name in names}

    def is_configured(self, name: str) -> bool:
        """Check if a secret is configured (has a value)."""
        return self.get(name) is not None

    def get_auth_secrets(self) -> dict[str, str | None]:
        """Get all authentication-related secrets."""
        auth_secrets = [
            "JWT_SECRET_KEY",
            "JWT_REFRESH_SECRET",
            "GOOGLE_OAUTH_CLIENT_ID",
            "GOOGLE_OAUTH_CLIENT_SECRET",
            "GITHUB_OAUTH_CLIENT_ID",
            "GITHUB_OAUTH_CLIENT_SECRET",
        ]
        return self.get_secrets(auth_secrets)

    def get_billing_secrets(self) -> dict[str, str | None]:
        """Get all billing-related secrets."""
        billing_secrets = [
            "STRIPE_SECRET_KEY",
            "STRIPE_WEBHOOK_SECRET",
            "STRIPE_PRICE_STARTER",
            "STRIPE_PRICE_PROFESSIONAL",
            "STRIPE_PRICE_ENTERPRISE",
        ]
        return self.get_secrets(billing_secrets)


# Global singleton instance with thread-safe initialization
_manager: SecretManager | None = None
_manager_lock = threading.Lock()


def get_secret_manager() -> SecretManager:
    """Get the global secret manager instance (thread-safe)."""
    global _manager
    if _manager is None:
        with _manager_lock:
            # Double-checked locking pattern
            if _manager is None:
                _manager = SecretManager()
    return _manager


def reset_secret_manager() -> None:
    """Reset the global secret manager (for testing)."""
    global _manager
    _manager = None


def get_secret(
    name: str,
    default: str | None = None,
    strict: bool | None = None,
) -> str | None:
    """
    Get a secret value.

    This is the main entry point for getting secrets throughout the application.
    Caching happens inside SecretManager (AWS secrets are loaded once on first access).

    Args:
        name: Secret name (e.g., "JWT_SECRET_KEY")
        default: Default value if not found
        strict: Override strict mode for this call (None = use global setting)

    Returns:
        Secret value or default

    Raises:
        SecretNotFoundError: If strict mode is enabled for a critical secret
            and it's not found in AWS Secrets Manager

    Example:
        jwt_secret = get_secret("JWT_SECRET_KEY")
        stripe_key = get_secret("STRIPE_SECRET_KEY", "")

        # Force non-strict for local development
        api_key = get_secret("API_KEY", strict=False)
    """
    return get_secret_manager().get(name, default, strict=strict)


def hydrate_env_from_secrets(
    names: list[str] | None = None,
    overwrite: bool = False,
) -> dict[str, str]:
    """
    Load secrets into environment variables.

    This allows legacy code that reads os.getenv/os.environ to prefer
    Secrets Manager values (when available), with .env as fallback.

    Args:
        names: Optional list of secret names to hydrate. Defaults to MANAGED_SECRETS.
        overwrite: If True, overwrite existing env vars (default False).

    Returns:
        Dict of secrets hydrated into environment.
    """
    hydrated: dict[str, str] = {}
    try:
        manager = get_secret_manager()
        target_names = names or list(MANAGED_SECRETS)
        for name in target_names:
            if not overwrite and os.environ.get(name):
                continue
            try:
                # Use strict=False so strict-mode environments don't raise here.
                # hydrate_env_from_secrets is best-effort pre-loading; strict enforcement
                # happens when the application actively calls get_secret() for the value.
                value = manager.get(name, strict=False)
            except Exception:  # noqa: BLE001
                continue
            if value:
                os.environ[name] = value
                hydrated[name] = value
    except (OSError, RuntimeError, ValueError):
        # Best-effort: don't block startup on secrets hydration.
        return hydrated

    return hydrated


def get_required_secret(name: str) -> str:
    """
    Get a required secret value.

    Args:
        name: Secret name

    Returns:
        Secret value

    Raises:
        ValueError: If secret is not found
    """
    return get_secret_manager().get_required(name)


def clear_secret_cache() -> None:
    """Clear the secret cache (for testing or secret rotation)."""
    reset_secret_manager()


def refresh_secrets() -> None:
    """Force refresh secrets from AWS Secrets Manager.

    Call this after rotating secrets in AWS to ensure the application
    picks up the new values immediately.
    """
    get_secret_manager().refresh()


def get_secret_access_log() -> list[dict[str, Any]]:
    """Get the secret access log for audit purposes (SOC 2 compliance).

    Returns:
        List of access log entries with timestamp, secret_name, source, and success.
    """
    return get_secret_manager().get_access_log()
