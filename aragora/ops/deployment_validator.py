"""Deployment Validator for Aragora.

Provides comprehensive runtime validation for production deployments,
including connectivity checks, API key validation, and component health.

Usage:
    from aragora.ops import validate_deployment, quick_health_check

    # Full validation (async)
    result = await validate_deployment()
    if not result.ready:
        for issue in result.issues:
            print(f"[{issue.severity}] {issue.component}: {issue.message}")

    # Quick sync check for startup
    if not quick_health_check():
        sys.exit(1)

Production Requirements (from docs/PRODUCTION_READINESS.md):
- JWT secret: 32+ characters, not a default/weak value
- AI providers: At least one of ANTHROPIC_API_KEY, OPENAI_API_KEY configured
- Database: Supabase URL/Key or PostgreSQL DSN for production persistence
- Redis: Required for distributed state (rate limiting, sessions, leader election)
- CORS: Restricted origins (no localhost in production)
- Rate limiting: Configured and enabled
- TLS/HTTPS: Enforced in production
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class DeploymentNotReadyError(RuntimeError):
    """Raised when strict deployment validation fails.

    Contains the full ValidationResult for inspection.
    """

    def __init__(self, result: ValidationResult) -> None:
        critical = [i for i in result.issues if i.severity.value == "critical"]
        summary = "; ".join(f"{i.component}: {i.message}" for i in critical)
        super().__init__(f"Deployment validation failed: {summary}")
        self.result = result


# Known weak/default JWT secrets that should not be used in production
WEAK_JWT_SECRETS = {
    "secret",
    "jwt-secret",
    "your-secret-key",
    "change-me",
    "changeme",
    "development",
    "dev-secret",
    "test-secret",
    "super-secret",
    "supersecret",
    "aragora-secret",
    "aragora",
}


class Severity(str, Enum):
    """Issue severity levels."""

    CRITICAL = "critical"  # Blocks deployment
    WARNING = "warning"  # Should be addressed
    INFO = "info"  # Informational


class ComponentStatus(str, Enum):
    """Component health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ValidationIssue:
    """A validation issue found during deployment check."""

    component: str
    message: str
    severity: Severity
    suggestion: str | None = None


@dataclass
class ComponentHealth:
    """Health status of a single component."""

    name: str
    status: ComponentStatus
    latency_ms: float | None = None
    message: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Complete deployment validation result."""

    ready: bool  # True if deployment can proceed
    live: bool  # True if basic health checks pass
    issues: list[ValidationIssue] = field(default_factory=list)
    components: list[ComponentHealth] = field(default_factory=list)
    validated_at: float = field(default_factory=time.time)
    validation_duration_ms: float = 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "ready": self.ready,
            "live": self.live,
            "issues": [
                {
                    "component": i.component,
                    "message": i.message,
                    "severity": i.severity.value,
                    "suggestion": i.suggestion,
                }
                for i in self.issues
            ],
            "components": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "latency_ms": c.latency_ms,
                    "message": c.message,
                    "metadata": c.metadata,
                }
                for c in self.components
            ],
            "validated_at": self.validated_at,
            "validation_duration_ms": self.validation_duration_ms,
        }


class DeploymentValidator:
    """Validates deployment readiness with runtime checks."""

    def __init__(self):
        self.issues: list[ValidationIssue] = []
        self.components: list[ComponentHealth] = []

    async def validate(self) -> ValidationResult:
        """Run all validation checks.

        Returns:
            ValidationResult with readiness status and any issues found
        """
        start = time.time()
        self.issues = []
        self.components = []

        # Determine environment mode once
        env = os.environ.get("ARAGORA_ENV", "development")
        self._is_production = env.lower() in ("production", "prod", "live")

        # Run all checks
        await self._check_environment()
        await self._check_jwt_secret()
        await self._check_storage()
        await self._check_database()
        await self._check_supabase()
        await self._check_redis()
        await self._check_api_keys()
        await self._check_encryption()
        await self._check_cors_security()
        await self._check_rate_limiting()
        await self._check_tls_settings()

        duration_ms = (time.time() - start) * 1000

        # Determine readiness
        critical_issues = [i for i in self.issues if i.severity == Severity.CRITICAL]
        ready = len(critical_issues) == 0

        # Determine liveness (basic health)
        unhealthy = [c for c in self.components if c.status == ComponentStatus.UNHEALTHY]
        live = len(unhealthy) == 0 or all(
            c.name in ("redis", "postgres")
            for c in unhealthy  # Optional components
        )

        return ValidationResult(
            ready=ready,
            live=live,
            issues=self.issues,
            components=self.components,
            validation_duration_ms=duration_ms,
        )

    async def _check_environment(self) -> None:
        """Check environment configuration."""
        env = os.environ.get("ARAGORA_ENV", "development")
        is_production = env.lower() in ("production", "prod", "live")

        self.components.append(
            ComponentHealth(
                name="environment",
                status=ComponentStatus.HEALTHY,
                metadata={"env": env, "is_production": is_production},
            )
        )

        # Check for debug mode in production
        if is_production and os.environ.get("ARAGORA_DEBUG", "").lower() in ("true", "1"):
            self.issues.append(
                ValidationIssue(
                    component="environment",
                    message="Debug mode enabled in production",
                    severity=Severity.WARNING,
                    suggestion="Set ARAGORA_DEBUG=false",
                )
            )

    async def _check_jwt_secret(self) -> None:
        """Check JWT secret configuration.

        Production requirements:
        - JWT secret must be at least 32 characters
        - Must not be a known weak/default value
        - Should have sufficient entropy (mixed case, numbers, special chars)
        """
        jwt_secret = os.environ.get("ARAGORA_JWT_SECRET") or os.environ.get("JWT_SECRET")

        if not jwt_secret:
            if self._is_production:
                self.components.append(
                    ComponentHealth(
                        name="jwt_secret",
                        status=ComponentStatus.UNHEALTHY,
                        message="JWT secret not configured",
                    )
                )
                self.issues.append(
                    ValidationIssue(
                        component="jwt_secret",
                        message="ARAGORA_JWT_SECRET required in production",
                        severity=Severity.CRITICAL,
                        suggestion='Generate: python -c "import secrets; print(secrets.token_urlsafe(48))"',
                    )
                )
            else:
                self.components.append(
                    ComponentHealth(
                        name="jwt_secret",
                        status=ComponentStatus.UNKNOWN,
                        message="Not configured (using default in development)",
                    )
                )
            return

        # Check minimum length (32 characters)
        if len(jwt_secret) < 32:
            self.components.append(
                ComponentHealth(
                    name="jwt_secret",
                    status=ComponentStatus.UNHEALTHY,
                    message=f"JWT secret too short ({len(jwt_secret)} chars, need 32+)",
                )
            )
            severity = Severity.CRITICAL if self._is_production else Severity.WARNING
            self.issues.append(
                ValidationIssue(
                    component="jwt_secret",
                    message=f"JWT secret must be at least 32 characters (currently {len(jwt_secret)})",
                    severity=severity,
                    suggestion='Generate: python -c "import secrets; print(secrets.token_urlsafe(48))"',
                )
            )
            return

        # Check for weak/default secrets
        if jwt_secret.lower() in WEAK_JWT_SECRETS:
            self.components.append(
                ComponentHealth(
                    name="jwt_secret",
                    status=ComponentStatus.UNHEALTHY,
                    message="JWT secret is a known weak/default value",
                )
            )
            severity = Severity.CRITICAL if self._is_production else Severity.WARNING
            self.issues.append(
                ValidationIssue(
                    component="jwt_secret",
                    message="JWT secret is a known weak/default value - easily guessable",
                    severity=severity,
                    suggestion='Generate: python -c "import secrets; print(secrets.token_urlsafe(48))"',
                )
            )
            return

        # Check entropy (basic check for character variety)
        has_upper = bool(re.search(r"[A-Z]", jwt_secret))
        has_lower = bool(re.search(r"[a-z]", jwt_secret))
        has_digit = bool(re.search(r"\d", jwt_secret))
        has_special = bool(re.search(r"[^A-Za-z0-9]", jwt_secret))
        variety_count = sum([has_upper, has_lower, has_digit, has_special])

        if variety_count < 2 and self._is_production:
            self.components.append(
                ComponentHealth(
                    name="jwt_secret",
                    status=ComponentStatus.DEGRADED,
                    message="JWT secret has low entropy",
                    metadata={"length": len(jwt_secret), "variety_count": variety_count},
                )
            )
            self.issues.append(
                ValidationIssue(
                    component="jwt_secret",
                    message="JWT secret has low entropy (use mixed case, numbers, special chars)",
                    severity=Severity.WARNING,
                    suggestion='Generate: python -c "import secrets; print(secrets.token_urlsafe(48))"',
                )
            )
        else:
            self.components.append(
                ComponentHealth(
                    name="jwt_secret",
                    status=ComponentStatus.HEALTHY,
                    metadata={
                        "length": len(jwt_secret),
                        "variety_count": variety_count,
                        "meets_requirements": True,
                    },
                )
            )

    async def _check_storage(self) -> None:
        """Check storage paths are writable."""
        start = time.time()

        # Check data directory
        from aragora.persistence.db_config import get_nomic_dir

        data_path = get_nomic_dir().resolve()
        data_dir = str(data_path)

        try:
            data_path.mkdir(parents=True, exist_ok=True)
            test_file = data_path / ".write_test"
            test_file.write_text("test")
            test_file.unlink()

            self.components.append(
                ComponentHealth(
                    name="storage",
                    status=ComponentStatus.HEALTHY,
                    latency_ms=(time.time() - start) * 1000,
                    metadata={"data_dir": str(data_path.absolute())},
                )
            )
        except (OSError, PermissionError) as e:
            self.components.append(
                ComponentHealth(
                    name="storage",
                    status=ComponentStatus.UNHEALTHY,
                    message=f"Cannot write to data directory: {e}",
                )
            )
            self.issues.append(
                ValidationIssue(
                    component="storage",
                    message=f"Data directory not writable: {data_dir}",
                    severity=Severity.CRITICAL,
                    suggestion=f"Ensure {data_dir} exists and is writable",
                )
            )

    async def _check_database(self) -> None:
        """Check database connectivity."""
        start = time.time()
        db_backend = os.environ.get("ARAGORA_DB_BACKEND", "sqlite").lower()

        if db_backend in ("postgres", "postgresql"):
            await self._check_postgres()
        else:
            # SQLite - just verify we can create/access the database
            try:
                import sqlite3

                from aragora.persistence.db_config import DatabaseType, get_db_path

                db_path = get_db_path(DatabaseType.DEBATES).resolve()

                # Ensure directory exists
                db_path.parent.mkdir(parents=True, exist_ok=True)

                # Test connection
                conn = sqlite3.connect(str(db_path), timeout=5.0)
                cursor = conn.execute("SELECT 1")
                cursor.fetchone()
                conn.close()

                self.components.append(
                    ComponentHealth(
                        name="database",
                        status=ComponentStatus.HEALTHY,
                        latency_ms=(time.time() - start) * 1000,
                        metadata={"backend": "sqlite", "path": str(db_path)},
                    )
                )
            except (OSError, ImportError, RuntimeError) as e:
                self.components.append(
                    ComponentHealth(
                        name="database",
                        status=ComponentStatus.UNHEALTHY,
                        message=str(e),
                        metadata={"backend": "sqlite"},
                    )
                )
                self.issues.append(
                    ValidationIssue(
                        component="database",
                        message=f"SQLite database error: {e}",
                        severity=Severity.CRITICAL,
                    )
                )

    async def _check_postgres(self) -> None:
        """Check PostgreSQL connectivity."""
        start = time.time()
        dsn = os.environ.get("ARAGORA_POSTGRES_DSN") or os.environ.get("DATABASE_URL")

        if not dsn:
            self.components.append(
                ComponentHealth(
                    name="database",
                    status=ComponentStatus.UNHEALTHY,
                    message="PostgreSQL DSN not configured",
                    metadata={"backend": "postgres"},
                )
            )
            self.issues.append(
                ValidationIssue(
                    component="database",
                    message="PostgreSQL configured but no DSN provided",
                    severity=Severity.CRITICAL,
                    suggestion="Set ARAGORA_POSTGRES_DSN or DATABASE_URL",
                )
            )
            return

        try:
            import asyncpg

            conn = await asyncio.wait_for(asyncpg.connect(dsn), timeout=5.0)
            await conn.execute("SELECT 1")
            await conn.close()

            self.components.append(
                ComponentHealth(
                    name="database",
                    status=ComponentStatus.HEALTHY,
                    latency_ms=(time.time() - start) * 1000,
                    metadata={"backend": "postgres"},
                )
            )
        except asyncio.TimeoutError:
            self.components.append(
                ComponentHealth(
                    name="database",
                    status=ComponentStatus.UNHEALTHY,
                    message="Connection timeout",
                    metadata={"backend": "postgres"},
                )
            )
            self.issues.append(
                ValidationIssue(
                    component="database",
                    message="PostgreSQL connection timeout",
                    severity=Severity.CRITICAL,
                    suggestion="Check database host and network connectivity",
                )
            )
        except ImportError:
            self.components.append(
                ComponentHealth(
                    name="database",
                    status=ComponentStatus.UNHEALTHY,
                    message="asyncpg not installed",
                    metadata={"backend": "postgres"},
                )
            )
            self.issues.append(
                ValidationIssue(
                    component="database",
                    message="asyncpg package not installed",
                    severity=Severity.CRITICAL,
                    suggestion="pip install asyncpg",
                )
            )
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
            self.components.append(
                ComponentHealth(
                    name="database",
                    status=ComponentStatus.UNHEALTHY,
                    message=str(e),
                    metadata={"backend": "postgres"},
                )
            )
            self.issues.append(
                ValidationIssue(
                    component="database",
                    message=f"PostgreSQL connection failed: {e}",
                    severity=Severity.CRITICAL,
                )
            )

    async def _check_supabase(self) -> None:
        """Check Supabase configuration for production persistence."""
        supabase_url = os.environ.get("SUPABASE_URL")
        supabase_key = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

        if supabase_url and supabase_key:
            # Validate URL format
            if not supabase_url.startswith("https://"):
                self.components.append(
                    ComponentHealth(
                        name="supabase",
                        status=ComponentStatus.DEGRADED,
                        message="Supabase URL should use HTTPS",
                        metadata={"url_configured": True, "key_configured": True},
                    )
                )
                if self._is_production:
                    self.issues.append(
                        ValidationIssue(
                            component="supabase",
                            message="Supabase URL should use HTTPS in production",
                            severity=Severity.WARNING,
                            suggestion="Use https:// prefix for SUPABASE_URL",
                        )
                    )
            else:
                self.components.append(
                    ComponentHealth(
                        name="supabase",
                        status=ComponentStatus.HEALTHY,
                        message="Supabase configured",
                        metadata={"url_configured": True, "key_configured": True},
                    )
                )
        elif self._is_production:
            # Check if we have alternative database config
            has_postgres = os.environ.get("ARAGORA_POSTGRES_DSN") or os.environ.get("DATABASE_URL")
            if not has_postgres:
                self.components.append(
                    ComponentHealth(
                        name="supabase",
                        status=ComponentStatus.UNKNOWN,
                        message="Supabase not configured (no alternative database either)",
                    )
                )
                self.issues.append(
                    ValidationIssue(
                        component="supabase",
                        message="No production database configured (Supabase or PostgreSQL)",
                        severity=Severity.WARNING,
                        suggestion="Set SUPABASE_URL/SUPABASE_KEY or DATABASE_URL for production persistence",
                    )
                )
            else:
                self.components.append(
                    ComponentHealth(
                        name="supabase",
                        status=ComponentStatus.UNKNOWN,
                        message="Supabase not configured (using PostgreSQL instead)",
                    )
                )
        else:
            self.components.append(
                ComponentHealth(
                    name="supabase",
                    status=ComponentStatus.UNKNOWN,
                    message="Not configured (optional in development)",
                )
            )

    async def _check_redis(self) -> None:
        """Check Redis connectivity.

        In production with distributed state (multi-instance or HA), Redis is required for:
        - Session storage
        - Rate limiting state
        - Control plane leader election
        - Debate origin tracking
        - Distributed caching
        """
        start = time.time()
        redis_url = os.environ.get("ARAGORA_REDIS_URL") or os.environ.get("REDIS_URL")

        # Check if distributed state is required
        multi_instance = os.environ.get("ARAGORA_MULTI_INSTANCE", "").lower() in (
            "true",
            "1",
            "yes",
        )
        single_instance = os.environ.get("ARAGORA_SINGLE_INSTANCE", "").lower() in (
            "true",
            "1",
            "yes",
        )
        distributed_required = self._is_production and multi_instance and not single_instance

        if not redis_url:
            if distributed_required:
                self.components.append(
                    ComponentHealth(
                        name="redis",
                        status=ComponentStatus.UNHEALTHY,
                        message="Redis required for distributed state but not configured",
                    )
                )
                self.issues.append(
                    ValidationIssue(
                        component="redis",
                        message="REDIS_URL required for distributed state (multi-instance mode)",
                        severity=Severity.CRITICAL,
                        suggestion="Set REDIS_URL or set ARAGORA_SINGLE_INSTANCE=true for single-node",
                    )
                )
            elif self._is_production:
                self.components.append(
                    ComponentHealth(
                        name="redis",
                        status=ComponentStatus.DEGRADED,
                        message="Redis not configured - using in-memory state",
                    )
                )
                self.issues.append(
                    ValidationIssue(
                        component="redis",
                        message="Redis not configured - state will be lost on restart",
                        severity=Severity.WARNING,
                        suggestion="Set REDIS_URL for durable session/rate-limit state",
                    )
                )
            else:
                self.components.append(
                    ComponentHealth(
                        name="redis",
                        status=ComponentStatus.UNKNOWN,
                        message="Not configured (optional in development)",
                    )
                )
            return

        try:
            import redis.asyncio as redis_client

            client = redis_client.from_url(redis_url)
            await asyncio.wait_for(client.ping(), timeout=5.0)

            # Get server info for metadata
            info = await client.info("server")
            redis_version = info.get("redis_version", "unknown")
            await client.close()

            self.components.append(
                ComponentHealth(
                    name="redis",
                    status=ComponentStatus.HEALTHY,
                    latency_ms=(time.time() - start) * 1000,
                    metadata={
                        "version": redis_version,
                        "distributed_required": distributed_required,
                    },
                )
            )
        except asyncio.TimeoutError:
            self.components.append(
                ComponentHealth(
                    name="redis",
                    status=ComponentStatus.UNHEALTHY,
                    message="Connection timeout",
                )
            )
            severity = Severity.CRITICAL if distributed_required else Severity.WARNING
            self.issues.append(
                ValidationIssue(
                    component="redis",
                    message="Redis connection timeout",
                    severity=severity,
                    suggestion="Check Redis host and network connectivity",
                )
            )
        except ImportError:
            self.components.append(
                ComponentHealth(
                    name="redis",
                    status=ComponentStatus.UNKNOWN,
                    message="redis package not installed",
                )
            )
            if distributed_required:
                self.issues.append(
                    ValidationIssue(
                        component="redis",
                        message="redis package not installed but required for distributed state",
                        severity=Severity.CRITICAL,
                        suggestion="pip install redis",
                    )
                )
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
            self.components.append(
                ComponentHealth(
                    name="redis",
                    status=ComponentStatus.UNHEALTHY,
                    message=str(e),
                )
            )
            severity = Severity.CRITICAL if distributed_required else Severity.WARNING
            self.issues.append(
                ValidationIssue(
                    component="redis",
                    message=f"Redis connection failed: {e}",
                    severity=severity,
                )
            )

    async def _check_api_keys(self) -> None:
        """Check API key configuration."""
        providers = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }

        configured = []
        for name, env_var in providers.items():
            if os.environ.get(env_var):
                configured.append(name)

        if not configured:
            self.components.append(
                ComponentHealth(
                    name="api_keys",
                    status=ComponentStatus.UNHEALTHY,
                    message="No AI provider API keys configured",
                )
            )
            self.issues.append(
                ValidationIssue(
                    component="api_keys",
                    message="No AI provider API keys configured",
                    severity=Severity.CRITICAL,
                    suggestion="Set at least one of: ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY",
                )
            )
        else:
            self.components.append(
                ComponentHealth(
                    name="api_keys",
                    status=ComponentStatus.HEALTHY,
                    metadata={"providers": configured},
                )
            )

    async def _check_encryption(self) -> None:
        """Check encryption configuration."""
        env = os.environ.get("ARAGORA_ENV", "development")
        is_production = env.lower() in ("production", "prod", "live")
        encryption_key = os.environ.get("ARAGORA_ENCRYPTION_KEY")

        if is_production and not encryption_key:
            self.components.append(
                ComponentHealth(
                    name="encryption",
                    status=ComponentStatus.UNHEALTHY,
                    message="Encryption key not configured for production",
                )
            )
            self.issues.append(
                ValidationIssue(
                    component="encryption",
                    message="ARAGORA_ENCRYPTION_KEY required in production",
                    severity=Severity.CRITICAL,
                    suggestion="Generate a 32-byte hex key: openssl rand -hex 32",
                )
            )
        elif encryption_key:
            # Validate key format
            try:
                key_bytes = bytes.fromhex(encryption_key)
                if len(key_bytes) != 32:
                    raise ValueError("Key must be 32 bytes")

                self.components.append(
                    ComponentHealth(
                        name="encryption",
                        status=ComponentStatus.HEALTHY,
                        metadata={"configured": True},
                    )
                )
            except (ValueError, TypeError) as e:
                self.components.append(
                    ComponentHealth(
                        name="encryption",
                        status=ComponentStatus.UNHEALTHY,
                        message=f"Invalid encryption key format: {e}",
                    )
                )
                self.issues.append(
                    ValidationIssue(
                        component="encryption",
                        message="Invalid ARAGORA_ENCRYPTION_KEY format",
                        severity=Severity.CRITICAL,
                        suggestion="Key must be 64 hex characters (32 bytes)",
                    )
                )
        else:
            self.components.append(
                ComponentHealth(
                    name="encryption",
                    status=ComponentStatus.UNKNOWN,
                    message="Not configured (optional in development)",
                )
            )

    async def _check_cors_security(self) -> None:
        """Check CORS and security settings.

        Production requirements:
        - CORS origins should not include localhost/127.0.0.1
        - CORS origins should be explicitly restricted (not *)
        - Secure headers should be enabled
        """
        allowed_origins = os.environ.get("ARAGORA_ALLOWED_ORIGINS", "")
        cors_allow_all = os.environ.get("ARAGORA_CORS_ALLOW_ALL", "").lower() in ("true", "1")

        issues_found: list[str] = []
        metadata: dict = {
            "origins_configured": bool(allowed_origins),
            "allow_all": cors_allow_all,
        }

        if cors_allow_all:
            if self._is_production:
                issues_found.append("CORS allows all origins (*)")
                self.issues.append(
                    ValidationIssue(
                        component="cors",
                        message="CORS allows all origins - security risk in production",
                        severity=Severity.CRITICAL,
                        suggestion="Set ARAGORA_ALLOWED_ORIGINS to specific domains, disable ARAGORA_CORS_ALLOW_ALL",
                    )
                )
        elif allowed_origins:
            origins_list = [o.strip() for o in allowed_origins.split(",")]
            metadata["origins_count"] = len(origins_list)

            # Check for localhost in production
            # validation checklist, not a bind address
            localhost_patterns = ["localhost", "127.0.0.1", "0.0.0.0", "::1"]
            has_localhost = any(
                any(pattern in origin.lower() for pattern in localhost_patterns)
                for origin in origins_list
            )

            if has_localhost and self._is_production:
                issues_found.append("CORS origins include localhost")
                self.issues.append(
                    ValidationIssue(
                        component="cors",
                        message="CORS origins include localhost - remove for production",
                        severity=Severity.WARNING,
                        suggestion="Remove localhost/127.0.0.1 from ARAGORA_ALLOWED_ORIGINS",
                    )
                )

            # Check for wildcard in origins
            if "*" in origins_list and self._is_production:
                issues_found.append("CORS origins include wildcard (*)")
                self.issues.append(
                    ValidationIssue(
                        component="cors",
                        message="CORS origins include wildcard (*) - security risk",
                        severity=Severity.CRITICAL,
                        suggestion="Replace * with specific domain list in ARAGORA_ALLOWED_ORIGINS",
                    )
                )

            metadata["has_localhost"] = has_localhost
        elif self._is_production:
            # No origins configured in production
            issues_found.append("CORS origins not configured")
            self.issues.append(
                ValidationIssue(
                    component="cors",
                    message="ARAGORA_ALLOWED_ORIGINS not set - CORS will be restrictive",
                    severity=Severity.INFO,
                    suggestion="Set ARAGORA_ALLOWED_ORIGINS to your frontend domain(s)",
                )
            )

        # Check security headers
        secure_headers_disabled = os.environ.get(
            "ARAGORA_DISABLE_SECURITY_HEADERS", ""
        ).lower() in ("true", "1")
        if secure_headers_disabled and self._is_production:
            issues_found.append("Security headers disabled")
            self.issues.append(
                ValidationIssue(
                    component="cors",
                    message="Security headers disabled in production",
                    severity=Severity.WARNING,
                    suggestion="Remove ARAGORA_DISABLE_SECURITY_HEADERS",
                )
            )
        metadata["security_headers_disabled"] = secure_headers_disabled

        # Determine component status
        if any(i.severity == Severity.CRITICAL for i in self.issues if i.component == "cors"):
            status = ComponentStatus.UNHEALTHY
        elif issues_found:
            status = ComponentStatus.DEGRADED
        else:
            status = ComponentStatus.HEALTHY

        self.components.append(
            ComponentHealth(
                name="cors",
                status=status,
                message=", ".join(issues_found) if issues_found else "CORS configured correctly",
                metadata=metadata,
            )
        )

    async def _check_rate_limiting(self) -> None:
        """Check rate limiting configuration.

        Production requirements:
        - Rate limiting should be enabled
        - Reasonable limits should be set
        - Redis backend recommended for distributed deployments
        """
        rate_limit = os.environ.get("ARAGORA_RATE_LIMIT")
        ip_rate_limit = os.environ.get("ARAGORA_IP_RATE_LIMIT")
        rate_limit_disabled = os.environ.get("ARAGORA_DISABLE_RATE_LIMIT", "").lower() in (
            "true",
            "1",
        )
        rate_limit_backend = os.environ.get("ARAGORA_RATE_LIMIT_BACKEND", "memory")

        metadata: dict = {
            "enabled": not rate_limit_disabled,
            "token_limit": rate_limit,
            "ip_limit": ip_rate_limit,
            "backend": rate_limit_backend,
        }

        if rate_limit_disabled:
            if self._is_production:
                self.components.append(
                    ComponentHealth(
                        name="rate_limiting",
                        status=ComponentStatus.UNHEALTHY,
                        message="Rate limiting disabled in production",
                        metadata=metadata,
                    )
                )
                self.issues.append(
                    ValidationIssue(
                        component="rate_limiting",
                        message="Rate limiting disabled - API vulnerable to abuse",
                        severity=Severity.CRITICAL,
                        suggestion="Remove ARAGORA_DISABLE_RATE_LIMIT",
                    )
                )
            else:
                self.components.append(
                    ComponentHealth(
                        name="rate_limiting",
                        status=ComponentStatus.DEGRADED,
                        message="Rate limiting disabled (development only)",
                        metadata=metadata,
                    )
                )
            return

        issues_found: list[str] = []

        # Check if rate limits are set
        if not rate_limit and not ip_rate_limit:
            if self._is_production:
                issues_found.append("Using default rate limits")
                self.issues.append(
                    ValidationIssue(
                        component="rate_limiting",
                        message="Rate limits not explicitly configured - using defaults",
                        severity=Severity.INFO,
                        suggestion="Set ARAGORA_RATE_LIMIT and ARAGORA_IP_RATE_LIMIT for production",
                    )
                )

        # Check backend for distributed deployments
        redis_url = os.environ.get("ARAGORA_REDIS_URL") or os.environ.get("REDIS_URL")
        multi_instance = os.environ.get("ARAGORA_MULTI_INSTANCE", "").lower() in (
            "true",
            "1",
            "yes",
        )

        if multi_instance and rate_limit_backend == "memory":
            issues_found.append("Memory backend with multi-instance")
            self.issues.append(
                ValidationIssue(
                    component="rate_limiting",
                    message="Memory-based rate limiting with multi-instance - limits not shared",
                    severity=Severity.WARNING,
                    suggestion="Set ARAGORA_RATE_LIMIT_BACKEND=redis and configure REDIS_URL",
                )
            )
        elif rate_limit_backend == "redis" and not redis_url:
            issues_found.append("Redis backend without URL")
            self.issues.append(
                ValidationIssue(
                    component="rate_limiting",
                    message="Redis rate limit backend configured but REDIS_URL not set",
                    severity=Severity.WARNING,
                    suggestion="Set REDIS_URL or change ARAGORA_RATE_LIMIT_BACKEND to memory",
                )
            )

        # Validate rate limit values if set
        if rate_limit:
            try:
                limit_val = int(rate_limit)
                if limit_val < 10:
                    issues_found.append(f"Very low token rate limit ({limit_val})")
                elif limit_val > 10000:
                    issues_found.append(f"Very high token rate limit ({limit_val})")
                metadata["token_limit_parsed"] = limit_val
            except ValueError:
                issues_found.append("Invalid token rate limit format")
                self.issues.append(
                    ValidationIssue(
                        component="rate_limiting",
                        message=f"Invalid ARAGORA_RATE_LIMIT value: {rate_limit}",
                        severity=Severity.WARNING,
                        suggestion="Set to a positive integer (requests per minute)",
                    )
                )

        # Determine status
        if issues_found:
            status = ComponentStatus.DEGRADED
        else:
            status = ComponentStatus.HEALTHY

        self.components.append(
            ComponentHealth(
                name="rate_limiting",
                status=status,
                message=", ".join(issues_found) if issues_found else "Rate limiting configured",
                metadata=metadata,
            )
        )

    async def _check_tls_settings(self) -> None:
        """Check TLS/HTTPS settings.

        Production requirements:
        - HTTPS should be enforced (via reverse proxy or direct)
        - TLS version should be 1.2+
        - HSTS should be enabled
        """
        # Check TLS enforcement settings
        force_https = os.environ.get("ARAGORA_FORCE_HTTPS", "").lower() in ("true", "1")
        tls_enabled = os.environ.get("ARAGORA_TLS_ENABLED", "").lower() in ("true", "1")
        hsts_enabled = os.environ.get("ARAGORA_HSTS_ENABLED", "").lower() not in ("false", "0")
        behind_proxy = os.environ.get("ARAGORA_BEHIND_PROXY", "").lower() in ("true", "1")
        trust_proxy_headers = os.environ.get("ARAGORA_TRUST_PROXY_HEADERS", "").lower() in (
            "true",
            "1",
        )

        metadata: dict = {
            "force_https": force_https,
            "tls_enabled": tls_enabled,
            "hsts_enabled": hsts_enabled,
            "behind_proxy": behind_proxy,
            "trust_proxy_headers": trust_proxy_headers,
        }

        issues_found: list[str] = []

        if self._is_production:
            # In production, we need either direct TLS or proxy with HTTPS enforcement
            if not tls_enabled and not behind_proxy:
                issues_found.append("No TLS configuration")
                self.issues.append(
                    ValidationIssue(
                        component="tls",
                        message="Neither direct TLS nor reverse proxy configured for HTTPS",
                        severity=Severity.WARNING,
                        suggestion="Set ARAGORA_TLS_ENABLED=true or ARAGORA_BEHIND_PROXY=true",
                    )
                )

            if behind_proxy and not trust_proxy_headers:
                issues_found.append("Proxy mode without header trust")
                self.issues.append(
                    ValidationIssue(
                        component="tls",
                        message="Behind proxy but not trusting X-Forwarded headers",
                        severity=Severity.INFO,
                        suggestion="Set ARAGORA_TRUST_PROXY_HEADERS=true if using trusted reverse proxy",
                    )
                )

            if not force_https and not behind_proxy:
                issues_found.append("HTTPS not enforced")
                self.issues.append(
                    ValidationIssue(
                        component="tls",
                        message="HTTPS not enforced - HTTP connections allowed",
                        severity=Severity.WARNING,
                        suggestion="Set ARAGORA_FORCE_HTTPS=true to redirect HTTP to HTTPS",
                    )
                )

            if not hsts_enabled:
                issues_found.append("HSTS disabled")
                self.issues.append(
                    ValidationIssue(
                        component="tls",
                        message="HSTS disabled - browser security feature not active",
                        severity=Severity.INFO,
                        suggestion="Enable HSTS by removing ARAGORA_HSTS_ENABLED=false",
                    )
                )

            # Check TLS certificate paths if direct TLS is enabled
            if tls_enabled:
                cert_path = os.environ.get("ARAGORA_TLS_CERT_PATH")
                key_path = os.environ.get("ARAGORA_TLS_KEY_PATH")

                if not cert_path or not key_path:
                    issues_found.append("TLS paths not configured")
                    self.issues.append(
                        ValidationIssue(
                            component="tls",
                            message="TLS enabled but certificate/key paths not set",
                            severity=Severity.CRITICAL,
                            suggestion="Set ARAGORA_TLS_CERT_PATH and ARAGORA_TLS_KEY_PATH",
                        )
                    )
                else:
                    # Verify files exist
                    cert_exists = Path(cert_path).exists() if cert_path else False
                    key_exists = Path(key_path).exists() if key_path else False
                    metadata["cert_exists"] = cert_exists
                    metadata["key_exists"] = key_exists

                    if not cert_exists or not key_exists:
                        issues_found.append("TLS files not found")
                        self.issues.append(
                            ValidationIssue(
                                component="tls",
                                message=f"TLS certificate/key files not found "
                                f"(cert: {cert_exists}, key: {key_exists})",
                                severity=Severity.CRITICAL,
                                suggestion="Verify certificate and key file paths exist",
                            )
                        )

        # Determine status
        critical_issues = any(
            i.severity == Severity.CRITICAL for i in self.issues if i.component == "tls"
        )
        if critical_issues:
            status = ComponentStatus.UNHEALTHY
        elif issues_found:
            status = ComponentStatus.DEGRADED
        elif self._is_production and (tls_enabled or behind_proxy):
            status = ComponentStatus.HEALTHY
        else:
            status = (
                ComponentStatus.UNKNOWN if not self._is_production else ComponentStatus.DEGRADED
            )

        self.components.append(
            ComponentHealth(
                name="tls",
                status=status,
                message=(
                    ", ".join(issues_found)
                    if issues_found
                    else (
                        "TLS configured correctly"
                        if self._is_production
                        else "TLS not required in development"
                    )
                ),
                metadata=metadata,
            )
        )

    async def readiness_check(self) -> ValidationResult:
        """Fast readiness probe -- 3 checks only (storage, database, API keys).

        Suitable for Kubernetes /readyz probes. Runs ~100ms vs ~500ms for full validate().
        """
        start = time.time()
        self.issues = []
        self.components = []
        self._is_production = os.environ.get("ARAGORA_ENV", "development").lower() in (
            "production",
            "prod",
            "live",
        )

        await self._check_storage()
        await self._check_database()
        await self._check_api_keys()

        duration_ms = (time.time() - start) * 1000
        critical_issues = [i for i in self.issues if i.severity == Severity.CRITICAL]

        return ValidationResult(
            ready=len(critical_issues) == 0,
            live=True,
            issues=self.issues,
            components=self.components,
            validation_duration_ms=duration_ms,
        )


async def readiness_check() -> ValidationResult:
    """Fast readiness check (3 checks: storage, database, API keys)."""
    validator = DeploymentValidator()
    return await validator.readiness_check()


async def validate_deployment(*, strict: bool = False) -> ValidationResult:
    """Run deployment validation.

    Args:
        strict: If True and validation finds critical issues, raise
            DeploymentNotReadyError instead of returning a failed result.

    Returns:
        ValidationResult with readiness status

    Raises:
        DeploymentNotReadyError: When strict=True and result.ready is False.
    """
    validator = DeploymentValidator()
    result = await validator.validate()
    if strict and not result.ready:
        raise DeploymentNotReadyError(result)
    return result


def quick_health_check() -> bool:
    """Quick synchronous health check for startup.

    Returns:
        True if basic health checks pass
    """
    try:
        # Check minimum requirements
        from aragora.config.validator import validate_all

        result = validate_all(strict=False)

        if result.get("errors"):
            for error in result["errors"]:
                logger.error("Configuration error: %s", error)
            return False

        return True
    except (ImportError, ValueError, TypeError, OSError, RuntimeError) as e:
        logger.error("Health check failed: %s", e)
        return False


__all__ = [
    "DeploymentValidator",
    "DeploymentNotReadyError",
    "ValidationResult",
    "ValidationIssue",
    "ComponentHealth",
    "ComponentStatus",
    "Severity",
    "validate_deployment",
    "readiness_check",
    "quick_health_check",
]
