"""
Secret custody integration for Aragora.

This module provides secure secret management with multiple fallback strategies:
1. Protected files in a configured mounted directory
2. AWS Secrets Manager (when explicitly or automatically enabled)
3. Environment variables (local development)
4. Default values (for non-sensitive config)

Security Features:
- Strict mode: Critical secrets MUST come from approved managed custody in production
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
import stat
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast

logger = logging.getLogger(__name__)

_MAX_MOUNTED_SECRET_BYTES = 64 * 1024
_AVAILABLE_SECRET_SOURCES = frozenset({"mounted_file", "aws", "managed_cache", "env"})


def _mfa_prompt_allowed(*, isatty: bool, env: Mapping[str, str] | None = None) -> bool:
    """Whether an interactive AWS MFA prompt is permissible in this process.

    A non-interactive process (cron automation, headless conductor, a background
    evidence pass) must NEVER block on ``getpass`` for an MFA code — it hangs
    forever with no TTY to answer it. This is the silent failure that wedged every
    automated Secrets Manager load: the process appears to "run" but is stuck on an
    invisible prompt. Allowed only when attached to a TTY, or when explicitly
    overridden via ``ARAGORA_AWS_ALLOW_MFA_PROMPT`` (escape hatch for odd setups).
    """
    resolved: Mapping[str, str] = os.environ if env is None else env
    override = str(resolved.get("ARAGORA_AWS_ALLOW_MFA_PROMPT", "")).strip().lower()
    if override in ("1", "true", "yes"):
        return True
    return isatty


def _fail_fast_mfa_prompter(prompt: str = "") -> str:
    """Replaces botocore's interactive ``getpass`` MFA prompter in non-interactive
    processes so AWS assume-role-with-MFA *fails fast* (caught → fall back to env /
    .env secrets) instead of blocking forever on a TTY that isn't there."""
    raise RuntimeError(
        "AWS assume-role needs an interactive MFA code but this process has no TTY; "
        "skipping Secrets Manager and falling back to environment/.env secrets. "
        "Run interactively, pre-export an AWS session, or set "
        "ARAGORA_USE_SECRETS_MANAGER=false to silence."
    )


def _has_controlling_tty() -> bool:
    """Whether a controlling terminal is reachable for an interactive prompt.

    botocore's MFA prompt uses ``getpass``, which reads ``/dev/tty`` (the controlling
    terminal), NOT stdin — so ``sys.stdin.isatty()`` is the wrong question: a process
    with redirected stdin but a live terminal (``python app.py </dev/null`` in an SSH
    shell) could still prompt successfully. Probe ``/dev/tty`` directly to match what
    getpass will actually do, so we only fail-fast when there is genuinely no terminal
    (cron, nohup, a detached daemon).
    """
    try:
        fd = os.open("/dev/tty", os.O_RDWR)
    except OSError:
        return False
    os.close(fd)
    return True


# Import botocore exceptions for proper error handling
# These are optional - if not installed, we use Exception as fallback
_BOTOCORE_AVAILABLE = False
try:
    from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped, import-not-found]

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
        "ARAGORA_API_TOKEN",
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
        "GOOGLE_API_KEY",
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
# These are high-value secrets where env var fallback could indicate a security issue.
#
# Hardening note (2026-04-17, HIGH-GRAVITY incident response): LLM API keys
# were added to this set because the Anthropic key leak demonstrated that
# local plaintext copies are a real attack surface. In strict mode, a missing
# AWS Secrets Manager entry will now raise SecretNotFoundError instead of
# silently consuming a stale .env value.
CRITICAL_SECRETS = frozenset(
    {
        # Authentication - Compromise allows session forging
        "JWT_SECRET_KEY",
        "JWT_REFRESH_SECRET",
        "ARAGORA_JWT_SECRET",
        "ARAGORA_API_TOKEN",
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
        # LLM API keys - Compromise allows direct spend + model abuse
        # (added 2026-04-17 after HIGH-GRAVITY leak of an Anthropic key)
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "XAI_API_KEY",
        "GROK_API_KEY",
        "MISTRAL_API_KEY",
        "DEEPSEEK_API_KEY",
        "KIMI_API_KEY",
    }
)


class SecretNotFoundError(Exception):
    """Raised when a critical secret is not found in approved managed custody."""

    def __init__(self, name: str, message: str | None = None):
        self.name = name
        if message:
            super().__init__(message)
        else:
            super().__init__(
                f"Critical secret '{name}' not found in approved managed secret custody. "
                f"In production, critical secrets must be stored in protected mounted "
                f"files or AWS Secrets Manager, not environment variables. Configure "
                f"ARAGORA_SECRETS_DIR or AWS Secrets Manager, or set "
                f"ARAGORA_SECRETS_STRICT=false to disable strict mode (not recommended)."
            )


class SecretSourceError(Exception):
    """Raised when an explicitly configured managed-secret source is unsafe."""


@dataclass(frozen=True)
class SecretPresence:
    """Presence-only secret status for safe health reporting."""

    name: str
    source: str
    critical: bool
    managed: bool

    @property
    def available(self) -> bool:
        """Whether the secret is available from any allowed custody backend."""
        return is_secret_presence_available(self)


def is_secret_presence_available(presence: SecretPresence) -> bool:
    """Interpret presence without enumerating custody backends in consumers."""
    return presence.source in _AVAILABLE_SECRET_SOURCES


def is_strict_mode() -> bool:
    """
    Check if strict secrets mode is enabled.

    Strict mode is enabled by default in production/staging environments.
    In strict mode, critical secrets MUST come from approved managed custody,
    not environment variables.

    Returns:
        True if strict mode is enabled
    """
    # Check explicit override first
    explicit = (os.environ.get("ARAGORA_SECRETS_STRICT") or "").lower()
    if explicit in ("false", "0", "no"):
        return False
    if explicit in ("true", "1", "yes"):
        return True

    # Default: strict in production/staging
    env = (os.environ.get("ARAGORA_ENV") or os.environ.get("ARAGORA_ENVIRONMENT") or "").lower()
    return env in ("production", "prod", "staging", "stage")


def is_critical_secret(name: str) -> bool:
    """Check if a secret is classified as critical."""
    return name in CRITICAL_SECRETS


@dataclass
class SecretsConfig:
    """Configuration for secrets management."""

    # Provider-neutral mounted-file settings
    secrets_dir: str | None = None

    # AWS Secrets Manager settings
    aws_region: str = "us-east-1"
    aws_regions: list[str] = field(default_factory=list)
    secret_name: str = "aragora/production"  # noqa: S105 -- AWS Secrets Manager path
    use_aws: bool = False

    # Cache settings
    cache_ttl_seconds: int = 300

    # AWS client settings
    aws_connect_timeout_seconds: float = 2.0
    aws_read_timeout_seconds: float = 2.0
    aws_max_attempts: int = 1

    @classmethod
    def from_env(cls) -> SecretsConfig:
        """Load config from environment.

        AWS Secrets Manager is opt-in unless the process is running in an
        AWS-managed runtime. A production/staging environment name alone never
        triggers an AWS probe.

        Set ARAGORA_USE_SECRETS_MANAGER=true to force-enable it anywhere, or
        false to disable it explicitly.
        """

        def _env_text(name: str, default: str = "") -> str:
            value = os.environ.get(name)
            return value if isinstance(value, str) and value else default

        def _env_float(name: str, default: float) -> float:
            try:
                return float(_env_text(name, str(default)))
            except ValueError:
                return default

        def _env_int(name: str, default: int) -> int:
            try:
                return int(_env_text(name, str(default)))
            except ValueError:
                return default

        secrets_dir = _env_text("ARAGORA_SECRETS_DIR") or None
        use_flag = _env_text("ARAGORA_USE_SECRETS_MANAGER")
        if use_flag:
            use_aws = use_flag.lower() in ("true", "1", "yes")
        else:
            use_aws = bool(_env_text("AWS_EXECUTION_ENV") or _env_text("AWS_LAMBDA_FUNCTION_NAME"))
        if is_strict_mode() and not secrets_dir and not use_aws:
            logger.warning(
                "Strict secrets mode is enabled but no managed custody backend is configured. "
                "Set ARAGORA_SECRETS_DIR or explicitly enable AWS Secrets Manager."
            )

        primary_region = _env_text("AWS_REGION") or _env_text("AWS_DEFAULT_REGION") or "us-east-1"
        raw_regions = _env_text("ARAGORA_SECRET_REGIONS")
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
            secrets_dir=secrets_dir,
            aws_region=primary_region,
            aws_regions=regions,
            secret_name=_env_text("ARAGORA_SECRET_NAME", "aragora/production"),
            use_aws=use_aws,
            aws_connect_timeout_seconds=_env_float(
                "ARAGORA_AWS_SECRET_CONNECT_TIMEOUT_SECONDS", 2.0
            ),
            aws_read_timeout_seconds=_env_float("ARAGORA_AWS_SECRET_READ_TIMEOUT_SECONDS", 2.0),
            aws_max_attempts=max(1, _env_int("ARAGORA_AWS_SECRET_MAX_ATTEMPTS", 1)),
        )


class SecretManager:
    """
    Manages secrets from multiple sources with fallback.

    Priority order:
    1. Protected mounted files (if configured)
    2. AWS Secrets Manager (if enabled)
    3. Environment variables
    4. Default values (for non-sensitive config)

    Features:
    - Automatic cache expiration based on TTL
    - Audit logging for secret access (SOC 2 compliance)
    - Thread-safe secret access
    """

    def __init__(self, config: SecretsConfig | None = None):
        self.config = config or SecretsConfig.from_env()
        self._aws_clients: dict[str, Any] = {}
        self._last_aws_load_succeeded = False
        self._last_aws_load_transient_failure = False
        self._last_aws_load_authoritative_failure = False
        self._managed_sources_healthy = False
        self._cached_secrets: dict[str, str] = {}
        self._cached_secret_sources: dict[str, str] = {}
        self._cache_timestamp: float = 0.0
        self._initialized = False
        self._lock = threading.Lock()
        self._access_log: list[dict[str, Any]] = []
        self._max_access_log_size = 1000
        self._warned_env_secrets: set[str] = set()

    def _open_secrets_directory(self) -> int:
        """Open and validate the configured directory without following symlinks."""
        configured = self.config.secrets_dir
        if not configured or not os.path.isabs(configured):
            raise SecretSourceError("ARAGORA_SECRETS_DIR must be an absolute directory")
        if (
            os.name != "posix"
            or not hasattr(os, "O_DIRECTORY")
            or not hasattr(os, "O_NOFOLLOW")
            or os.open not in os.supports_dir_fd
        ):
            raise SecretSourceError("ARAGORA_SECRETS_DIR requires POSIX descriptor safety")

        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
        trusted_uids = {0, os.geteuid()}
        components = [part for part in configured.split(os.path.sep) if part]
        if not components:
            raise SecretSourceError("ARAGORA_SECRETS_DIR must not identify the filesystem root")
        if any(component in {".", ".."} for component in components):
            raise SecretSourceError("ARAGORA_SECRETS_DIR must not contain dot components")
        try:
            current_fd = os.open(os.path.sep, flags)
        except OSError as exc:
            raise SecretSourceError("Filesystem root could not be opened safely") from exc
        try:
            for index, component in enumerate(components):
                next_fd = os.open(component, flags | os.O_NOFOLLOW, dir_fd=current_fd)
                try:
                    component_stat = os.fstat(next_fd)
                    component_mode = stat.S_IMODE(component_stat.st_mode)
                    is_final = index == len(components) - 1
                    if not stat.S_ISDIR(component_stat.st_mode):
                        raise SecretSourceError("ARAGORA_SECRETS_DIR must identify a directory")
                    if component_stat.st_uid not in trusted_uids:
                        raise SecretSourceError(
                            "ARAGORA_SECRETS_DIR components must have trusted ownership"
                        )
                    if component_mode & 0o022 and (is_final or not component_mode & stat.S_ISVTX):
                        raise SecretSourceError(
                            "ARAGORA_SECRETS_DIR components must not be writable by peers"
                        )
                except (OSError, SecretSourceError):
                    os.close(next_fd)
                    raise
                os.close(current_fd)
                current_fd = next_fd
            return current_fd
        except OSError as exc:
            os.close(current_fd)
            raise SecretSourceError(
                "ARAGORA_SECRETS_DIR could not be opened without following symlinks"
            ) from exc
        except SecretSourceError:
            os.close(current_fd)
            raise

    def _read_mounted_secret(self, directory_fd: int, name: str) -> str | None:
        """Read one managed secret through a validated no-follow descriptor."""
        if name not in MANAGED_SECRETS or os.path.basename(name) != name:
            raise SecretSourceError("Refusing an unmanaged mounted-secret filename")

        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        try:
            fd = os.open(name, flags, dir_fd=directory_fd)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise SecretSourceError(f"Mounted secret '{name}' could not be opened safely") from exc

        try:
            file_stat = os.fstat(fd)
            file_mode = stat.S_IMODE(file_stat.st_mode)
            if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
                raise SecretSourceError(f"Mounted secret '{name}' must be a single-link file")
            if file_stat.st_uid not in {0, os.geteuid()}:
                raise SecretSourceError(f"Mounted secret '{name}' must have trusted ownership")
            if not file_mode & stat.S_IRUSR or file_mode & ~0o600:
                raise SecretSourceError(
                    f"Mounted secret '{name}' must use owner-readable, owner-only permissions"
                )
            if file_stat.st_size > _MAX_MOUNTED_SECRET_BYTES:
                raise SecretSourceError(f"Mounted secret '{name}' exceeds the size limit")

            payload = bytearray()
            while len(payload) <= _MAX_MOUNTED_SECRET_BYTES:
                chunk = os.read(fd, min(8192, _MAX_MOUNTED_SECRET_BYTES + 1 - len(payload)))
                if not chunk:
                    break
                payload.extend(chunk)
            if len(payload) > _MAX_MOUNTED_SECRET_BYTES:
                raise SecretSourceError(f"Mounted secret '{name}' exceeds the size limit")
            try:
                value = bytes(payload).decode("utf-8").rstrip("\r\n")
            except UnicodeDecodeError as exc:
                raise SecretSourceError(f"Mounted secret '{name}' must contain UTF-8 text") from exc
            if not value.strip():
                raise SecretSourceError(f"Mounted secret '{name}' must not be empty")
            return value
        except OSError as exc:
            raise SecretSourceError(f"Mounted secret '{name}' could not be read safely") from exc
        finally:
            os.close(fd)

    def _load_from_mounted_directory(self) -> dict[str, str]:
        """Load present managed filenames from the configured protected directory."""
        if not self.config.secrets_dir:
            return {}
        directory_fd = self._open_secrets_directory()
        try:
            secrets = {
                name: value
                for name in MANAGED_SECRETS
                if (value := self._read_mounted_secret(directory_fd, name)) is not None
            }
        finally:
            os.close(directory_fd)
        logger.info("Loaded %d secrets from protected mounted files", len(secrets))
        return secrets

    def _load_managed_sources(self) -> tuple[dict[str, str], dict[str, str]]:
        """Load enabled sources and merge them in custody-precedence order."""
        self._managed_sources_healthy = False
        mounted_secrets = self._load_from_mounted_directory() if self.config.secrets_dir else {}
        aws_secrets = self._load_from_aws() if self.config.use_aws else {}
        if aws_secrets:
            self._last_aws_load_succeeded = True
        self._managed_sources_healthy = bool(self.config.secrets_dir or self.config.use_aws) and (
            not self.config.use_aws or self._last_aws_load_succeeded
        )
        if (
            self.config.use_aws
            and self._last_aws_load_transient_failure
            and not self._last_aws_load_succeeded
            and not self._last_aws_load_authoritative_failure
        ):
            aws_secrets = {
                name: value
                for name, value in self._cached_secrets.items()
                if self._cached_secret_sources.get(name) == "aws"
            }
            if aws_secrets:
                logger.warning("Preserving last known AWS secret cache after refresh failure")
        combined = {**aws_secrets, **mounted_secrets}
        sources = {name: "aws" for name in aws_secrets}
        sources.update({name: "mounted_file" for name in mounted_secrets})
        return combined, sources

    def _cached_entry(self, name: str) -> tuple[str | None, str]:
        """Return one coherent value/source snapshot across concurrent refreshes."""
        with self._lock:
            value = self._cached_secrets.get(name)
            source = self._cached_secret_sources.get(name)
            if source is None:
                source = "managed_cache"
            return value, source

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
            "source": source,  # managed backend, env, default, or failure classification
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
            import boto3  # type: ignore[import-untyped, import-not-found]
            from botocore.config import Config  # type: ignore[import-untyped, import-not-found]

            config = Config(
                connect_timeout=self.config.aws_connect_timeout_seconds,
                read_timeout=self.config.aws_read_timeout_seconds,
                retries={
                    "max_attempts": self.config.aws_max_attempts,
                    "mode": "standard",
                },
            )
            client = self._build_client(boto3, region, config)
            # Don't cache a fail-closed None: a later retry (e.g. after credentials
            # become available, or in a different process state) must be able to
            # re-attempt Secrets Manager rather than be pinned to None for the
            # SecretManager instance's lifetime.
            if client is not None:
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

    def _build_client(self, boto3: Any, region: str, config: Any) -> Any:
        """Build the Secrets Manager client, neutering the interactive MFA prompt in
        non-interactive processes.

        A profile that requires assume-role-with-MFA (``AWS_PROFILE=aragora-secrets``)
        otherwise blocks on ``getpass`` with no TTY to answer — the silent hang that
        wedged every headless Secrets Manager load. Here, a non-interactive process
        installs :func:`_fail_fast_mfa_prompter` so resolution fails fast and the
        caller falls back to env/.env secrets. Interactive TTYs and MFA-free
        credential paths (instance roles, OIDC) are unaffected.
        """
        if _mfa_prompt_allowed(isatty=_has_controlling_tty()):
            return boto3.client("secretsmanager", region_name=region, config=config)
        try:
            # Reach botocore's session via boto3's own wrapper (``_session``) rather
            # than importing botocore.session directly — keeps this off the typed
            # import surface (boto3 is already an untyped/Any import).
            boto_session = boto3.Session()
            botocore_session = boto_session._session
            provider = botocore_session.get_component("credential_provider").get_provider(
                "assume-role"
            )
            provider._prompter = _fail_fast_mfa_prompter
            return boto_session.client("secretsmanager", region_name=region, config=config)
        except Exception:  # noqa: BLE001 - botocore internals vary by version
            # Fail CLOSED, not back to the hang-prone default client: if the guard
            # cannot be installed in a non-interactive process, returning
            # boto3.client() here would re-enter the exact getpass MFA hang this
            # exists to prevent. Returning None makes the caller fall back to
            # env/.env secrets instead.
            logger.warning(
                "could not install non-interactive MFA guard for %s; refusing the "
                "default client to avoid a getpass hang (using env/.env secrets)",
                region,
            )
            return None

    def _load_from_aws(self) -> dict[str, str]:
        """Load secrets from AWS Secrets Manager."""
        self._last_aws_load_succeeded = False
        self._last_aws_load_transient_failure = False
        self._last_aws_load_authoritative_failure = False
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
                self._last_aws_load_authoritative_failure = True
                secret_string = response.get("SecretString")
                if not isinstance(secret_string, str):
                    logger.error("AWS secret payload is not textual JSON (region=%s)", region)
                    return {}
                parsed = json.loads(secret_string)
                if not isinstance(parsed, dict) or not all(
                    isinstance(name, str) and isinstance(value, str)
                    for name, value in parsed.items()
                ):
                    logger.error("AWS secret payload is not a string map (region=%s)", region)
                    return {}
                secrets: dict[str, str] = parsed
                logger.info(
                    "Loaded %d secrets from AWS Secrets Manager (region=%s)",
                    len(secrets),
                    region,
                )
                self._last_aws_load_succeeded = True
                self._last_aws_load_transient_failure = False
                self._last_aws_load_authoritative_failure = False
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
                        self._last_aws_load_authoritative_failure = True
                        logger.warning(
                            "Secret '%s' not found in AWS (region=%s)",
                            self.config.secret_name,
                            region,
                        )
                        continue
                    if error_code == "AccessDeniedException":
                        logger.warning("Access denied to AWS Secrets Manager (region=%s)", region)
                        continue
                    if error_code in {
                        "InternalServiceError",
                        "RequestTimeout",
                        "ServiceUnavailable",
                        "ThrottlingException",
                    }:
                        self._last_aws_load_transient_failure = True
                    logger.error(
                        "AWS Secrets Manager error (region=%s): %s: %s", region, error_code, e
                    )
                else:
                    self._last_aws_load_transient_failure = True
                    logger.error(
                        "AWS/botocore error (region=%s): %s: %s", region, type(e).__name__, e
                    )
                continue
            except OSError as e:
                last_error = e
                self._last_aws_load_transient_failure = True
                logger.error(
                    "Unexpected error loading secrets (region=%s): %s: %s",
                    region,
                    type(e).__name__,
                    e,
                )
                continue
            except (RuntimeError, ValueError, KeyError) as e:
                # Catch remaining non-boto exceptions (e.g., config errors)
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
        """Initialize the secret manager and its enabled managed sources.

        Args:
            force_refresh: Force reload from managed sources even if cache is valid
        """
        import time

        with self._lock:
            # First initialization
            if not self._initialized:
                logger.debug(
                    "Initializing SecretManager: mounted_files=%s, use_aws=%s, "
                    "secret_name=%s, regions=%s",
                    bool(self.config.secrets_dir),
                    self.config.use_aws,
                    self.config.secret_name,
                    self.config.aws_regions,
                )
                if self.config.secrets_dir or self.config.use_aws:
                    self._cached_secrets, self._cached_secret_sources = self._load_managed_sources()
                    self._cache_timestamp = time.time()
                    if self._cached_secrets:
                        logger.info(
                            "Secrets cache initialized with %d secrets, TTL: %ds",
                            len(self._cached_secrets),
                            self.config.cache_ttl_seconds,
                        )
                    else:
                        logger.warning("Managed secrets cache initialized but empty")
                else:
                    logger.debug("Managed secret sources disabled; using environment variables")
                self._initialized = True
                return

            # Already initialized - check if an enabled managed source needs refresh.
            if not (self.config.secrets_dir or self.config.use_aws):
                return

            if self._cache_timestamp == 0.0 and not force_refresh:
                # Some callers and tests preseed _cached_secrets and mark the
                # manager initialized to model a known cache state without
                # touching live AWS. Treat that explicit initialization as
                # authoritative until the normal TTL window elapses.
                self._cache_timestamp = time.time()
                return

            needs_refresh = force_refresh or self._is_cache_expired()
            if not needs_refresh:
                return

            self._cached_secrets, self._cached_secret_sources = self._load_managed_sources()
            self._cache_timestamp = time.time()
            logger.debug("Secrets cache refreshed, TTL: %ss", self.config.cache_ttl_seconds)

    def refresh(self) -> None:
        """Force refresh enabled managed sources after secret rotation."""
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
                and it's not found in approved managed custody
        """
        self._initialize()

        # Determine if strict mode applies
        use_strict = strict if strict is not None else is_strict_mode()
        is_critical = is_critical_secret(name)

        # 1. Check the merged managed-source cache first.
        managed_value, managed_source = self._cached_entry(name)
        if managed_value is not None and managed_value.strip():
            self._log_access(name, managed_source, True)
            return managed_value

        if name in MANAGED_SECRETS:
            logger.debug("Managed secret cache miss")

        # 2. Check environment variable
        env_value = os.environ.get(name)

        # In strict mode, critical secrets MUST NOT come from env vars
        if use_strict and is_critical:
            if env_value is not None:
                # Log warning - env var exists but shouldn't be used
                logger.warning(
                    "SECURITY: Critical secret '%s' found in environment variable "
                    "but strict mode is enabled. This secret should be in approved "
                    "managed custody. Ignoring env var value.",
                    name,
                )
                self._log_access(name, "env_blocked", False)
            # Secret not in approved managed custody - raise error.
            self._log_access(name, "not_found_strict", False)
            raise SecretNotFoundError(name)

        # Non-strict mode or non-critical secret - allow env fallback
        if env_value is not None:
            if is_critical and name not in self._warned_env_secrets:
                self._warned_env_secrets.add(name)
                logger.warning(
                    "SECURITY: Critical secret '%s' loaded from environment variable. "
                    "Consider migrating to approved managed custody for production use.",
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

    def presence(self, name: str, strict: bool | None = None) -> SecretPresence:
        """Return a presence-only secret source without exposing the value.

        Sources are:
        - ``mounted_file``: available from a protected mounted file.
        - ``aws``: available from the current Secrets Manager cache.
        - ``managed_cache``: available from a pre-seeded cache with unknown provenance.
        - ``env``: available from process environment and allowed by mode.
        - ``blocked_by_strict_mode``: present in env but strict mode forbids using it.
        - ``missing``: unavailable from both AWS cache and env.
        """
        self._initialize()

        use_strict = strict if strict is not None else is_strict_mode()
        is_critical = is_critical_secret(name)
        managed_value, managed_source = self._cached_entry(name)
        env_value = os.environ.get(name)

        if managed_value is not None and managed_value.strip():
            source = managed_source
        elif use_strict and is_critical and env_value is not None and env_value.strip():
            source = "blocked_by_strict_mode"
        elif env_value is not None and env_value.strip():
            source = "env"
        else:
            source = "missing"

        presence = SecretPresence(
            name=name,
            source=source,
            critical=is_critical,
            managed=name in MANAGED_SECRETS,
        )
        self._log_access(name, f"presence_{source}", presence.available)
        return presence

    def presence_report(
        self, names: list[str] | tuple[str, ...], strict: bool | None = None
    ) -> list[SecretPresence]:
        """Return presence-only statuses for multiple secrets."""
        return [self.presence(name, strict=strict) for name in names]

    def is_usable(self, name: str, min_length: int = 8, strict: bool | None = None) -> bool:
        """Return whether a secret has a non-placeholder usable value.

        This intentionally returns only a boolean so health checks can decide
        provider readiness without exposing or logging secret values.
        """
        self._initialize()

        use_strict = strict if strict is not None else is_strict_mode()
        is_critical = is_critical_secret(name)
        managed_value, managed_source = self._cached_entry(name)
        if managed_value is not None:
            usable = len(managed_value.strip()) >= min_length
            self._log_access(name, f"usable_{managed_source}", usable)
            return usable

        env_value = os.environ.get(name)
        if use_strict and is_critical:
            if env_value is not None and env_value.strip():
                self._log_access(name, "usable_env_blocked", False)
            else:
                self._log_access(name, "usable_missing", False)
            return False

        usable = bool(env_value and len(env_value.strip()) >= min_length)
        self._log_access(name, "usable_env" if usable else "usable_missing", usable)
        return usable

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
    Caching happens inside SecretManager (managed secrets are loaded once on first access).

    Args:
        name: Secret name (e.g., "JWT_SECRET_KEY")
        default: Default value if not found
        strict: Override strict mode for this call (None = use global setting)

    Returns:
        Secret value or default

    Raises:
        SecretNotFoundError: If strict mode is enabled for a critical secret
            and it's not found in approved managed custody

    Example:
        jwt_secret = get_secret("JWT_SECRET_KEY")
        stripe_key = get_secret("STRIPE_SECRET_KEY", "")

        # Force non-strict for local development
        api_key = get_secret("API_KEY", strict=False)
    """
    return get_secret_manager().get(name, default, strict=strict)


def get_secret_presence(name: str, strict: bool | None = None) -> SecretPresence:
    """Get a presence-only secret status without returning the value."""
    return get_secret_manager().presence(name, strict=strict)


def is_secret_usable(name: str, min_length: int = 8, strict: bool | None = None) -> bool:
    """Return whether a secret is present with a usable non-placeholder value."""
    return get_secret_manager().is_usable(name, min_length=min_length, strict=strict)


def get_secret_presence_report(
    names: list[str] | tuple[str, ...],
    strict: bool | None = None,
) -> list[SecretPresence]:
    """Get presence-only secret statuses without returning values."""
    return get_secret_manager().presence_report(names, strict=strict)


def hydrate_env_from_secrets(
    names: list[str] | None = None,
    overwrite: bool = False,
) -> dict[str, str]:
    """
    Load secrets into environment variables.

    This allows legacy code that reads os.getenv/os.environ to prefer
    managed-custody values (when available), with .env as fallback.

    Args:
        names: Optional list of secret names to hydrate. Defaults to MANAGED_SECRETS.
        overwrite: If True, overwrite existing env vars (default False).

    Returns:
        Dict of secrets hydrated into environment.
    """
    hydrated: dict[str, str] = {}
    try:
        manager = get_secret_manager()
        manager._initialize()
        target_names = names or list(MANAGED_SECRETS)
        with manager._lock:
            cached_secrets = dict(manager._cached_secrets)
            cached_sources = dict(manager._cached_secret_sources)
            clear_unmanaged_env = manager._managed_sources_healthy or (
                manager.config.use_aws and manager._last_aws_load_authoritative_failure
            )
        use_strict = is_strict_mode()
        for name in target_names:
            if (
                not overwrite
                and os.environ.get(name)
                and not (use_strict and is_critical_secret(name))
            ):
                continue
            value: str | None
            if name in cached_secrets and cached_secrets[name].strip():
                value = cached_secrets[name]
                source = cached_sources.get(name, "managed_cache")
                manager._log_access(name, f"hydrate_{source}", True)
            elif use_strict and is_critical_secret(name):
                manager._log_access(name, "hydrate_env_blocked", False)
                if name in os.environ and clear_unmanaged_env:
                    logger.warning(
                        "SECURITY: Removing critical secret '%s' from the process environment "
                        "because strict managed custody is enabled.",
                        name,
                    )
                    os.environ.pop(name, None)
                elif name in os.environ:
                    manager._log_access(name, "hydrate_env_retained_source_unhealthy", False)
                    logger.warning(
                        "SECURITY: Retaining previously hydrated critical secret '%s' because "
                        "the configured managed source did not load successfully.",
                        name,
                    )
                continue
            else:
                value = os.environ.get(name)
                manager._log_access(name, "hydrate_env", bool(value))
            if value:
                os.environ[name] = value
                hydrated[name] = value
    except SecretSourceError:
        raise
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
    """Force refresh secrets from enabled managed custody.

    Call this after rotating managed secrets to ensure the application
    picks up the new values immediately.
    """
    get_secret_manager().refresh()


def get_secret_access_log() -> list[dict[str, Any]]:
    """Get the secret access log for audit purposes (SOC 2 compliance).

    Returns:
        List of access log entries with timestamp, secret_name, source, and success.
    """
    return get_secret_manager().get_access_log()
