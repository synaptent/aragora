"""
Doctor command - Comprehensive health checks for Aragora.

Checks:
- Python version and required packages
- API key configuration
- Database connectivity
- Redis availability
- Storage backends
- Server endpoints (if running)
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from aragora.config.provider_readiness import (
    PROVIDER_CREDENTIAL_SPECS,
    discover_provider_credentials,
)

HealthCheck = tuple[str, str, bool | None]

_AWS_SECRETS_PROBE_SIGNAL_ENV_VARS = (
    "ARAGORA_SECRET_NAME",
    "ARAGORA_SECRET_REGIONS",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AWS_PROFILE",
    "AWS_ACCESS_KEY_ID",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AWS_ROLE_ARN",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    "AWS_EXECUTION_ENV",
    "AWS_LAMBDA_FUNCTION_NAME",
)


@dataclass(frozen=True)
class _AwsSecretsPosture:
    """Presence-only summary of the AWS Secrets Manager provider posture.

    Never carries secret values — only whether a provider credential is
    resolvable from AWS Secrets Manager and which provider(s) are present.
    """

    available: bool
    providers: tuple[str, ...]
    detail: str
    # Whether the *runtime* credential path will actually honor AWS Secrets
    # Manager (``SecretsConfig.from_env().use_aws``). When False, the keys exist
    # in AWS but ``hydrate_env_from_secrets`` will NOT load them for this
    # process, so doctor must warn rather than green-light the posture.
    honored_by_runtime: bool = False


def _has_explicit_aws_secrets_probe_signal(
    *, runtime_use_aws: bool, aws_region: str, aws_regions: list[str], secret_name: str
) -> bool:
    """Return whether doctor should spend time probing AWS Secrets Manager."""

    if not aws_region and not aws_regions and not secret_name:
        return False
    if runtime_use_aws:
        return True
    return any(os.environ.get(name) for name in _AWS_SECRETS_PROBE_SIGNAL_ENV_VARS)


def _aws_secrets_provider_posture() -> _AwsSecretsPosture:
    """Detect whether provider keys are resolvable via AWS Secrets Manager.

    Per project policy the canonical local posture keeps provider keys in AWS
    Secrets Manager (not the process env), loaded via ``aragora.config.secrets``.
    Local runs leave AWS opt-out by default, so ``discover_provider_credentials``
    will not find env keys. This probe forces an AWS-backed ``SecretManager`` and
    uses the presence-only API so no secret value is ever read or logged.

    Returns an unavailable posture (never raises) when boto3 is missing, AWS is
    unreachable, or no provider secret is present — so a genuinely keyless
    machine still fails the doctor check.
    """

    try:
        from aragora.config.secrets import SecretManager, SecretsConfig
    except ImportError:
        return _AwsSecretsPosture(False, (), "")

    try:
        base = SecretsConfig.from_env()
    except (OSError, RuntimeError, ValueError):
        return _AwsSecretsPosture(False, (), "")

    # Does the *runtime* path honor AWS? hydrate_env_from_secrets respects the
    # env-derived use_aws; if it's False the keys won't actually be loaded.
    honored_by_runtime = bool(base.use_aws)

    # SecretsConfig supplies default region/secret values, so post-default config
    # fields cannot prove the user has an AWS posture. Avoid a network probe on
    # ordinary keyless local machines unless AWS loading is active or explicit
    # AWS/Secrets Manager environment is present.
    if not _has_explicit_aws_secrets_probe_signal(
        runtime_use_aws=honored_by_runtime,
        aws_region=base.aws_region,
        aws_regions=base.aws_regions,
        secret_name=base.secret_name,
    ):
        return _AwsSecretsPosture(False, (), "")

    # Force an AWS-backed lookup even in the default local opt-out posture, but
    # keep the bounded timeouts/region set from the environment configuration.
    config = SecretsConfig(
        aws_region=base.aws_region,
        aws_regions=list(base.aws_regions),
        secret_name=base.secret_name,
        use_aws=True,
        cache_ttl_seconds=base.cache_ttl_seconds,
        aws_connect_timeout_seconds=base.aws_connect_timeout_seconds,
        aws_read_timeout_seconds=base.aws_read_timeout_seconds,
        aws_max_attempts=base.aws_max_attempts,
    )

    try:
        manager = SecretManager(config)
        present: list[str] = []
        for spec in PROVIDER_CREDENTIAL_SPECS:
            for env_var in spec.env_vars:
                # presence(...) returns the source only, never the secret value.
                if manager.presence(env_var).source == "aws":
                    present.append(spec.provider)
                    break
    except Exception:  # noqa: BLE001 — diagnostic probe must never crash doctor
        return _AwsSecretsPosture(False, (), "")

    if not present:
        return _AwsSecretsPosture(False, (), "")

    detail = "via AWS Secrets Manager: " + ", ".join(present)
    return _AwsSecretsPosture(True, tuple(present), detail, honored_by_runtime)


def check_icon(ok: bool | None) -> str:
    """Return status icon."""
    if ok is True:
        return "\033[92m✓\033[0m"  # Green checkmark
    elif ok is False:
        return "\033[91m✗\033[0m"  # Red X
    return "\033[93m○\033[0m"  # Yellow circle (optional)


def print_section(title: str) -> None:
    """Print section header."""
    print(f"\n\033[1m{title}\033[0m")
    print("-" * 40)


def check_packages() -> list[HealthCheck]:
    """Check required and optional packages."""
    checks: list[HealthCheck] = []

    # Required packages
    required = ["aiohttp", "pydantic", "sqlite3", "asyncio"]
    for pkg in required:
        try:
            __import__(pkg)
            checks.append((pkg, "installed", True))
        except Exception as exc:  # noqa: BLE001 - doctor should surface broken imports, not crash
            checks.append((pkg, f"MISSING ({type(exc).__name__})", False))

    def _optional_package_check(pkg: str, label: str) -> None:
        # Optional probes must be presence checks only. Importing native-heavy
        # packages like torch can segfault or exhaust CI workers before doctor
        # can report a useful health summary.
        try:
            available = importlib.util.find_spec(pkg) is not None
        except Exception as exc:  # noqa: BLE001 - diagnostic probe must not crash doctor
            checks.append((label, f"not installed ({type(exc).__name__})", None))
            return

        if available:
            checks.append((label, "installed", True))
        else:
            checks.append((label, "not installed", None))

    # Optional ML packages
    optional_ml = ["torch", "transformers", "sentence_transformers"]
    for pkg in optional_ml:
        _optional_package_check(pkg, f"{pkg} (ML)")

    # Optional integrations
    optional_int = ["redis", "asyncpg", "boto3", "opentelemetry"]
    for pkg in optional_int:
        _optional_package_check(pkg, f"{pkg} (integration)")

    return checks


def check_api_keys(validate_live: bool = False) -> list[HealthCheck]:
    """Check API key configuration."""
    checks: list[HealthCheck] = []
    report = discover_provider_credentials()
    invalid_providers = []

    for provider in report.providers:
        env_label = "/".join(provider.checked_env_vars)
        if provider.configured:
            status = "configured"
            ok: bool | None = True
            if validate_live:
                from aragora.cli.api_keys import get_supported_provider_names, validate_provider_key

                validation_provider = "grok" if provider.provider == "xai" else provider.provider
                if validation_provider in set(get_supported_provider_names()):
                    validation_report = validate_provider_key(validation_provider)
                    status = f"{status}; live {validation_report.remote_status}"
                    if getattr(validation_report, "unverified", False):
                        # Key is present and format-valid but could not be
                        # verified live. Do NOT render as a green pass — report
                        # it as optional/unverified so a fabricated or unusable
                        # key is never counted as "ready".
                        status = f"{status} (present, unverified)"
                        ok = None
                    elif not validation_report.is_valid:
                        status = f"{status}: {validation_report.message}"
                        invalid_providers.append(provider.provider)
                        ok = False
                else:
                    # No live validator for this provider: present but unverified.
                    status = f"{status}; live skipped (present, unverified)"
                    ok = None
            checks.append((env_label, status, ok))
        else:
            checks.append((env_label, "not set", None))

    if invalid_providers:
        checks.append(
            ("LLM Provider", f"invalid provider(s): {', '.join(invalid_providers)}", False)
        )
    elif report.any_configured:
        configured = ", ".join(report.configured_providers)
        checks.append(("LLM Provider", f"configured: {configured}", True))
    else:
        # No provider key in env/.env. Before failing, recognize the canonical
        # local posture where keys live in AWS Secrets Manager (loaded via
        # aragora.config.secrets) instead of the process environment.
        posture = _aws_secrets_provider_posture()
        if posture.available and posture.honored_by_runtime:
            checks.append(("LLM Provider", posture.detail, True))
        elif posture.available:
            # Keys exist in AWS Secrets Manager but the runtime won't load them
            # (use_aws is disabled). Warn (optional/None) rather than green-light
            # a posture hydrate_env_from_secrets will not actually honor.
            checks.append(
                (
                    "LLM Provider",
                    posture.detail + " — present but ARAGORA_USE_SECRETS_MANAGER "
                    "is not enabled for this runtime; keys will not be loaded",
                    None,
                )
            )
        else:
            if report.discovery_errors:
                detail = f"credential discovery failed ({'; '.join(report.discovery_errors)})"
                checks.append(("LLM Provider", detail, False))
            elif validate_live:
                checks.append(
                    ("LLM Provider", "NO API KEY SET; live validation unavailable", False)
                )
            else:
                checks.append(
                    (
                        "LLM Provider",
                        "not configured (offline/demo mode available; required for live debates)",
                        None,
                    )
                )

    return checks


def check_storage() -> list[HealthCheck]:
    """Check storage backends."""
    checks: list[HealthCheck] = []

    # Check data directory
    data_dir = Path.home() / ".aragora"
    if data_dir.exists():
        checks.append(("Data directory", str(data_dir), True))
    else:
        checks.append(("Data directory", "will be created", None))

    # Check SQLite
    try:
        import sqlite3

        conn = sqlite3.connect(":memory:")
        conn.execute("SELECT 1")
        conn.close()
        checks.append(("SQLite", "working", True))
    except (OSError, RuntimeError) as e:
        checks.append(("SQLite", f"error: {e}", False))

    # Check PostgreSQL
    try:
        import asyncpg  # noqa: F401

        checks.append(("PostgreSQL driver", "available", True))
        if os.getenv("DATABASE_URL"):
            checks.append(("DATABASE_URL", "configured", True))
        else:
            checks.append(("DATABASE_URL", "not set (using SQLite)", None))
    except ImportError:
        checks.append(("PostgreSQL driver", "not installed", None))

    # Check Redis
    try:
        import redis  # noqa: F401

        checks.append(("Redis driver", "available", True))
        if os.getenv("ARAGORA_REDIS_URL"):
            checks.append(("ARAGORA_REDIS_URL", "configured", True))
        else:
            checks.append(("ARAGORA_REDIS_URL", "not set (using memory)", None))
    except ImportError:
        checks.append(("Redis driver", "not installed", None))

    return checks


async def check_server() -> list[HealthCheck]:
    """Check if server is running and responsive."""
    checks: list[HealthCheck] = []

    try:
        from aragora.server.http_client_pool import get_http_pool

        pool = get_http_pool()
        try:
            async with pool.get_session("health_check") as client:
                resp = await client.get("http://localhost:8080/health", timeout=5)
                if resp.status_code == 200:
                    checks.append(("Server (localhost:8080)", "running", True))
                else:
                    checks.append(
                        ("Server (localhost:8080)", f"unhealthy ({resp.status_code})", False)
                    )
        except Exception:  # noqa: BLE001 — diagnostic tool must never crash
            checks.append(("Server (localhost:8080)", "not running", None))
    except ImportError:
        checks.append(("Server check", "http pool not available", None))

    return checks


def check_environment() -> list[HealthCheck]:
    """Check environment configuration."""
    checks: list[HealthCheck] = []

    # Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks.append(("Python", py_ver, sys.version_info >= (3, 10)))

    # Environment
    env = os.getenv("ARAGORA_ENV", "development")
    checks.append(("Environment", env, True))

    # Debug mode
    debug = os.getenv("ARAGORA_DEBUG", "false").lower() == "true"
    checks.append(("Debug mode", "enabled" if debug else "disabled", True))

    return checks


def main(validate_keys: bool = False) -> int:
    """Run comprehensive health checks."""
    print("\n\033[1;36m" + "=" * 50 + "\033[0m")
    print("\033[1;36m       ARAGORA HEALTH CHECK\033[0m")
    print("\033[1;36m" + "=" * 50 + "\033[0m")

    all_ok = True
    all_checks = []

    # Environment
    print_section("Environment")
    env_checks = check_environment()
    all_checks.extend(env_checks)
    for name, status, ok in env_checks:
        print(f"  {check_icon(ok)} {name}: {status}")
        if ok is False:
            all_ok = False

    # Packages
    print_section("Packages")
    pkg_checks = check_packages()
    all_checks.extend(pkg_checks)
    for name, status, ok in pkg_checks:
        print(f"  {check_icon(ok)} {name}: {status}")
        if ok is False:
            all_ok = False

    # API Keys
    print_section("API Keys")
    key_checks = check_api_keys(validate_live=validate_keys)
    all_checks.extend(key_checks)
    for name, status, ok in key_checks:
        print(f"  {check_icon(ok)} {name}: {status}")
        if ok is False:
            all_ok = False

    # Storage
    print_section("Storage")
    storage_checks = check_storage()
    all_checks.extend(storage_checks)
    for name, status, ok in storage_checks:
        print(f"  {check_icon(ok)} {name}: {status}")
        if ok is False:
            all_ok = False

    # Server
    print_section("Server")
    try:
        server_checks = asyncio.run(check_server())
        all_checks.extend(server_checks)
        for name, status, ok in server_checks:
            print(f"  {check_icon(ok)} {name}: {status}")
            if ok is False:
                all_ok = False
    except Exception as e:  # noqa: BLE001 — doctor must never crash
        print(f"  {check_icon(None)} Server check: skipped ({type(e).__name__}: {e})")

    # Summary
    passed = sum(1 for _, _, ok in all_checks if ok is True)
    failed = sum(1 for _, _, ok in all_checks if ok is False)
    optional = sum(1 for _, _, ok in all_checks if ok is None)

    print("\n" + "=" * 50)
    print(f"\033[1mSummary:\033[0m {passed} passed, {failed} failed, {optional} optional")

    if all_ok:
        print("\n\033[92m✓ Aragora is ready to use!\033[0m\n")
    else:
        print("\n\033[91m✗ Some required checks failed. Please fix the issues above.\033[0m\n")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
