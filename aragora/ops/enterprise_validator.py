"""Enterprise Deployment Validator for Aragora.

Validates enterprise-specific features and configurations including:
- RBAC configuration and permissions
- Audit logging setup
- Multi-tenancy isolation
- Control plane readiness
- Channel integrations
- Observability stack

Usage:
    from aragora.ops import validate_enterprise_deployment

    result = await validate_enterprise_deployment()
    if not result.ready:
        for issue in result.issues:
            print(f"[{issue.severity}] {issue.component}: {issue.message}")
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from .deployment_validator import (
    ComponentHealth,
    ComponentStatus,
    Severity,
    ValidationIssue,
    ValidationResult,
)

logger = logging.getLogger(__name__)


async def validate_enterprise_deployment(
    skip_external: bool = False,
) -> ValidationResult:
    """
    Validate enterprise deployment configuration.

    Checks enterprise-specific features beyond basic deployment validation.

    Args:
        skip_external: Skip checks requiring external connectivity

    Returns:
        ValidationResult with issues and component health
    """
    issues: list[ValidationIssue] = []
    components: list[ComponentHealth] = []

    # Run all validations concurrently
    validators = [
        _validate_rbac_configuration(),
        _validate_audit_logging(),
        _validate_tenancy_configuration(),
        _validate_control_plane(),
        _validate_channel_integrations(),
        _validate_observability(),
    ]

    results = await asyncio.gather(*validators, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            logger.error("Validation error: %s", result)
            issues.append(
                ValidationIssue(
                    component="validator",
                    message=f"Validation error: {result}",
                    severity=Severity.WARNING,
                )
            )
        elif isinstance(result, tuple):
            component_issues, component_health = result
            issues.extend(component_issues)
            if component_health:
                components.append(component_health)

    # Determine overall readiness
    critical_count = sum(1 for i in issues if i.severity == Severity.CRITICAL)

    ready = critical_count == 0
    live = True  # Enterprise validation doesn't block liveness

    return ValidationResult(
        ready=ready,
        live=live,
        issues=issues,
        components=components,
        validated_at=time.time(),
    )


async def _validate_rbac_configuration() -> tuple[list[ValidationIssue], ComponentHealth | None]:
    """Validate RBAC configuration."""
    issues: list[ValidationIssue] = []
    start = time.time()

    try:
        # Check if RBAC module is available
        from aragora.rbac import defaults

        # Verify default roles exist
        if not hasattr(defaults, "DEFAULT_ROLES") or not defaults.DEFAULT_ROLES:
            issues.append(
                ValidationIssue(
                    component="rbac",
                    message="RBAC default roles not configured",
                    severity=Severity.WARNING,
                    suggestion="Ensure RBAC defaults module defines DEFAULT_ROLES",
                )
            )

        # Verify permissions are defined
        if not hasattr(defaults, "ALL_PERMISSIONS") or not defaults.ALL_PERMISSIONS:
            issues.append(
                ValidationIssue(
                    component="rbac",
                    message="RBAC permissions not configured",
                    severity=Severity.WARNING,
                    suggestion="Ensure RBAC defaults module defines ALL_PERMISSIONS",
                )
            )

        # Check for permission checker
        try:
            from aragora.rbac.checker import PermissionChecker  # noqa: F401

            # Checker is available
        except ImportError:
            issues.append(
                ValidationIssue(
                    component="rbac",
                    message="Permission checker not available",
                    severity=Severity.WARNING,
                    suggestion="Install RBAC module with permission checker",
                )
            )

        latency = (time.time() - start) * 1000
        status = ComponentStatus.HEALTHY if not issues else ComponentStatus.DEGRADED

        return issues, ComponentHealth(
            name="rbac",
            status=status,
            latency_ms=latency,
            message="RBAC configuration validated",
        )

    except ImportError:
        latency = (time.time() - start) * 1000
        issues.append(
            ValidationIssue(
                component="rbac",
                message="RBAC module not available",
                severity=Severity.INFO,
                suggestion="RBAC is optional - install if role-based access control is needed",
            )
        )
        return issues, ComponentHealth(
            name="rbac",
            status=ComponentStatus.UNKNOWN,
            latency_ms=latency,
            message="RBAC module not installed",
        )


async def _validate_audit_logging() -> tuple[list[ValidationIssue], ComponentHealth | None]:
    """Validate audit logging configuration."""
    issues: list[ValidationIssue] = []
    start = time.time()

    try:
        # Check for audit module
        from aragora.server.handlers.debates import auditing  # noqa: F401

        # Check for audit store configuration
        audit_enabled = os.getenv("ARAGORA_AUDIT_ENABLED", "true").lower() == "true"

        if not audit_enabled:
            issues.append(
                ValidationIssue(
                    component="audit",
                    message="Audit logging is disabled",
                    severity=Severity.WARNING,
                    suggestion="Set ARAGORA_AUDIT_ENABLED=true for compliance",
                )
            )

        # Check audit retention
        retention_days = int(os.getenv("ARAGORA_AUDIT_RETENTION_DAYS", "365"))
        if retention_days < 90:
            issues.append(
                ValidationIssue(
                    component="audit",
                    message=f"Audit retention period ({retention_days} days) may not meet compliance requirements",
                    severity=Severity.WARNING,
                    suggestion="Set ARAGORA_AUDIT_RETENTION_DAYS to at least 90 for SOC 2 compliance",
                )
            )

        latency = (time.time() - start) * 1000
        status = ComponentStatus.HEALTHY if not issues else ComponentStatus.DEGRADED

        return issues, ComponentHealth(
            name="audit",
            status=status,
            latency_ms=latency,
            message="Audit logging configuration validated",
        )

    except ImportError:
        latency = (time.time() - start) * 1000
        issues.append(
            ValidationIssue(
                component="audit",
                message="Audit module not available",
                severity=Severity.WARNING,
                suggestion="Audit logging is recommended for enterprise deployments",
            )
        )
        return issues, ComponentHealth(
            name="audit",
            status=ComponentStatus.UNKNOWN,
            latency_ms=latency,
            message="Audit module not installed",
        )


async def _validate_tenancy_configuration() -> tuple[list[ValidationIssue], ComponentHealth | None]:
    """Validate multi-tenancy configuration."""
    issues: list[ValidationIssue] = []
    start = time.time()

    try:
        from aragora.tenancy import isolation  # noqa: F401

        # Check tenant isolation mode
        isolation_mode = os.getenv("ARAGORA_TENANT_ISOLATION", "strict")

        if isolation_mode not in ("strict", "standard", "relaxed"):
            issues.append(
                ValidationIssue(
                    component="tenancy",
                    message=f"Unknown tenant isolation mode: {isolation_mode}",
                    severity=Severity.WARNING,
                    suggestion="Set ARAGORA_TENANT_ISOLATION to 'strict', 'standard', or 'relaxed'",
                )
            )

        if isolation_mode == "relaxed":
            issues.append(
                ValidationIssue(
                    component="tenancy",
                    message="Tenant isolation mode is 'relaxed' - data may be shared across tenants",
                    severity=Severity.WARNING,
                    suggestion="Use 'strict' or 'standard' isolation for production",
                )
            )

        latency = (time.time() - start) * 1000
        status = ComponentStatus.HEALTHY if not issues else ComponentStatus.DEGRADED

        return issues, ComponentHealth(
            name="tenancy",
            status=status,
            latency_ms=latency,
            message="Tenancy configuration validated",
        )

    except ImportError:
        latency = (time.time() - start) * 1000
        # Tenancy is optional for single-tenant deployments
        return [], ComponentHealth(
            name="tenancy",
            status=ComponentStatus.HEALTHY,
            latency_ms=latency,
            message="Multi-tenancy not configured (single-tenant mode)",
        )


async def _validate_control_plane() -> tuple[list[ValidationIssue], ComponentHealth | None]:
    """Validate control plane configuration."""
    issues: list[ValidationIssue] = []
    start = time.time()

    try:
        from aragora.control_plane import coordinator  # noqa: F401

        # Check Redis for distributed state
        redis_url = os.getenv("REDIS_URL") or os.getenv("ARAGORA_REDIS_URL")

        if not redis_url:
            issues.append(
                ValidationIssue(
                    component="control_plane",
                    message="Redis not configured - control plane will use local state only",
                    severity=Severity.WARNING,
                    suggestion="Set REDIS_URL for distributed control plane state",
                )
            )

        # Check for leader election in multi-instance deployments
        multi_instance = os.getenv("ARAGORA_MULTI_INSTANCE", "false").lower() == "true"
        if multi_instance and not redis_url:
            issues.append(
                ValidationIssue(
                    component="control_plane",
                    message="Multi-instance mode enabled but Redis not configured",
                    severity=Severity.CRITICAL,
                    suggestion="Redis is required for leader election in multi-instance deployments",
                )
            )

        latency = (time.time() - start) * 1000
        status = ComponentStatus.HEALTHY if not issues else ComponentStatus.DEGRADED
        if any(i.severity == Severity.CRITICAL for i in issues):
            status = ComponentStatus.UNHEALTHY

        return issues, ComponentHealth(
            name="control_plane",
            status=status,
            latency_ms=latency,
            message="Control plane configuration validated",
        )

    except ImportError:
        latency = (time.time() - start) * 1000
        return [], ComponentHealth(
            name="control_plane",
            status=ComponentStatus.HEALTHY,
            latency_ms=latency,
            message="Control plane not configured (standalone mode)",
        )


async def _validate_channel_integrations() -> tuple[list[ValidationIssue], ComponentHealth | None]:
    """Validate channel integration configurations."""
    issues: list[ValidationIssue] = []
    start = time.time()
    configured_channels: list[str] = []

    # Check Slack
    if os.getenv("SLACK_BOT_TOKEN"):
        configured_channels.append("slack")
        if not os.getenv("SLACK_SIGNING_SECRET"):
            issues.append(
                ValidationIssue(
                    component="channels",
                    message="Slack bot token configured but signing secret missing",
                    severity=Severity.WARNING,
                    suggestion="Set SLACK_SIGNING_SECRET for webhook verification",
                )
            )

    # Check Teams
    if os.getenv("TEAMS_BOT_ID") or os.getenv("MICROSOFT_APP_ID"):
        configured_channels.append("teams")
        if not os.getenv("TEAMS_APP_PASSWORD") and not os.getenv("MICROSOFT_APP_PASSWORD"):
            issues.append(
                ValidationIssue(
                    component="channels",
                    message="Teams bot configured but app password missing",
                    severity=Severity.WARNING,
                    suggestion="Set TEAMS_APP_PASSWORD for authentication",
                )
            )

    # Check Discord
    if os.getenv("DISCORD_BOT_TOKEN"):
        configured_channels.append("discord")

    # Check Telegram
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        configured_channels.append("telegram")

    # Check Email
    if os.getenv("SMTP_HOST") or os.getenv("SENDGRID_API_KEY"):
        configured_channels.append("email")

    latency = (time.time() - start) * 1000

    metadata: dict[str, Any] = {"configured_channels": configured_channels}

    if not configured_channels:
        return issues, ComponentHealth(
            name="channels",
            status=ComponentStatus.HEALTHY,
            latency_ms=latency,
            message="No external channels configured",
            metadata=metadata,
        )

    status = ComponentStatus.HEALTHY if not issues else ComponentStatus.DEGRADED

    return issues, ComponentHealth(
        name="channels",
        status=status,
        latency_ms=latency,
        message=f"Channels configured: {', '.join(configured_channels)}",
        metadata=metadata,
    )


async def _validate_observability() -> tuple[list[ValidationIssue], ComponentHealth | None]:
    """Validate observability stack configuration."""
    issues: list[ValidationIssue] = []
    start = time.time()
    features: list[str] = []

    # Check Prometheus metrics
    metrics_enabled = os.getenv("ARAGORA_METRICS_ENABLED", "true").lower() == "true"
    if metrics_enabled:
        features.append("prometheus")
    else:
        issues.append(
            ValidationIssue(
                component="observability",
                message="Prometheus metrics disabled",
                severity=Severity.INFO,
                suggestion="Enable metrics with ARAGORA_METRICS_ENABLED=true",
            )
        )

    # Check OpenTelemetry
    otel_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otel_endpoint:
        features.append("opentelemetry")
    else:
        issues.append(
            ValidationIssue(
                component="observability",
                message="OpenTelemetry tracing not configured",
                severity=Severity.INFO,
                suggestion="Set OTEL_EXPORTER_OTLP_ENDPOINT for distributed tracing",
            )
        )

    # Check Sentry
    sentry_dsn = os.getenv("SENTRY_DSN")
    if sentry_dsn:
        features.append("sentry")
    else:
        issues.append(
            ValidationIssue(
                component="observability",
                message="Sentry error tracking not configured",
                severity=Severity.INFO,
                suggestion="Set SENTRY_DSN for error tracking in production",
            )
        )

    # Check logging level
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    if log_level == "DEBUG":
        issues.append(
            ValidationIssue(
                component="observability",
                message="Debug logging enabled - may impact performance",
                severity=Severity.WARNING,
                suggestion="Set LOG_LEVEL=INFO or higher for production",
            )
        )

    latency = (time.time() - start) * 1000
    status = (
        ComponentStatus.HEALTHY
        if not any(i.severity == Severity.WARNING for i in issues)
        else ComponentStatus.DEGRADED
    )

    return issues, ComponentHealth(
        name="observability",
        status=status,
        latency_ms=latency,
        message=f"Observability features: {', '.join(features) if features else 'minimal'}",
        metadata={"features": features},
    )


def get_enterprise_health_summary() -> dict[str, Any]:
    """
    Get a quick synchronous summary of enterprise configuration.

    Returns:
        Dict with quick health indicators
    """
    return {
        "rbac_available": _check_rbac_available(),
        "audit_enabled": os.getenv("ARAGORA_AUDIT_ENABLED", "true").lower() == "true",
        "redis_configured": bool(os.getenv("REDIS_URL") or os.getenv("ARAGORA_REDIS_URL")),
        "multi_instance": os.getenv("ARAGORA_MULTI_INSTANCE", "false").lower() == "true",
        "metrics_enabled": os.getenv("ARAGORA_METRICS_ENABLED", "true").lower() == "true",
        "sentry_configured": bool(os.getenv("SENTRY_DSN")),
        "otel_configured": bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")),
    }


def _check_rbac_available() -> bool:
    """Check if RBAC module is available."""
    try:
        from aragora.rbac import defaults

        return bool(getattr(defaults, "DEFAULT_ROLES", None))
    except ImportError:
        return False
