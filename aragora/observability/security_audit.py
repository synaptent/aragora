"""
Security Audit Logger for Aragora.

Provides specialized audit logging for security-related events including:
- Authentication and authorization decisions
- Encryption operations and key management
- Secret access and modification
- RBAC policy changes
- Security incidents and alerts
- Data access patterns

This module wraps the immutable audit log to provide security-focused
convenience functions and enriched context for security events.

Usage:
    from aragora.observability.security_audit import (
        audit_auth_success,
        audit_auth_failure,
        audit_secret_access,
        audit_rbac_decision,
        audit_encryption_operation,
        audit_key_rotation,
        audit_security_incident,
    )

    # Log successful authentication
    await audit_auth_success(
        user_id="user_123",
        method="jwt",
        ip_address="192.168.1.1",
    )

    # Log secret access
    await audit_secret_access(
        actor="user_123",
        secret_type="api_key",
        store="integrations",
        operation="decrypt",
    )
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from aragora.observability.immutable_log import AuditEntry, get_audit_log
from aragora.observability.metrics.security import (
    record_auth_attempt,
    record_auth_failure,
    record_rbac_decision,
    record_encryption_operation,
    record_key_rotation,
    record_secret_access,
    record_security_incident,
    record_security_alert,
    record_blocked_request,
)

logger = logging.getLogger(__name__)

# Security event types
SECURITY_EVENTS = {
    # Authentication events
    "auth_success": "security.auth.success",
    "auth_failure": "security.auth.failure",
    "auth_logout": "security.auth.logout",
    "session_created": "security.session.created",
    "session_invalidated": "security.session.invalidated",
    "token_issued": "security.token.issued",
    "token_revoked": "security.token.revoked",
    # Authorization events
    "rbac_granted": "security.rbac.granted",
    "rbac_denied": "security.rbac.denied",
    "permission_checked": "security.permission.checked",
    "role_assigned": "security.role.assigned",
    "role_revoked": "security.role.revoked",
    # Encryption events
    "encryption_success": "security.encryption.success",
    "encryption_failure": "security.encryption.failure",
    "decryption_success": "security.decryption.success",
    "decryption_failure": "security.decryption.failure",
    # Key management events
    "key_generated": "security.key.generated",
    "key_rotated": "security.key.rotated",
    "key_accessed": "security.key.accessed",
    "key_deleted": "security.key.deleted",
    # Secret access events
    "secret_accessed": "security.secret.accessed",
    "secret_created": "security.secret.created",
    "secret_updated": "security.secret.updated",
    "secret_deleted": "security.secret.deleted",
    # Migration events
    "migration_started": "security.migration.started",
    "migration_completed": "security.migration.completed",
    "migration_record_encrypted": "security.migration.record_encrypted",
    "migration_error": "security.migration.error",
    # Security incident events
    "incident_detected": "security.incident.detected",
    "incident_escalated": "security.incident.escalated",
    "incident_resolved": "security.incident.resolved",
    "alert_triggered": "security.alert.triggered",
    "request_blocked": "security.request.blocked",
}

# =============================================================================
# Authentication Audit Functions
# =============================================================================


async def audit_auth_success(
    user_id: str,
    method: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
    workspace_id: str | None = None,
    correlation_id: str | None = None,
    **details: Any,
) -> AuditEntry:
    """
    Log a successful authentication.

    Args:
        user_id: ID of the authenticated user
        method: Authentication method (e.g., "jwt", "api_key", "oauth")
        ip_address: Client IP address
        user_agent: Client user agent
        workspace_id: Workspace being accessed
        correlation_id: Request correlation ID
        **details: Additional details

    Returns:
        The created audit entry
    """
    record_auth_attempt(method, success=True)

    return await get_audit_log().append(
        event_type=SECURITY_EVENTS["auth_success"],
        actor=user_id,
        actor_type="user",
        resource_type="authentication",
        resource_id=method,
        action="authenticate",
        details={
            "method": method,
            "success": True,
            **details,
        },
        ip_address=ip_address,
        user_agent=user_agent,
        workspace_id=workspace_id,
        correlation_id=correlation_id,
    )


async def audit_auth_failure(
    user_id: str | None,
    method: str,
    reason: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
    correlation_id: str | None = None,
    **details: Any,
) -> AuditEntry:
    """
    Log a failed authentication attempt.

    Args:
        user_id: ID of the user (if known)
        method: Authentication method attempted
        reason: Reason for failure (e.g., "invalid_token", "expired", "revoked")
        ip_address: Client IP address
        user_agent: Client user agent
        correlation_id: Request correlation ID
        **details: Additional details

    Returns:
        The created audit entry
    """
    record_auth_attempt(method, success=False)
    record_auth_failure(method, reason)

    return await get_audit_log().append(
        event_type=SECURITY_EVENTS["auth_failure"],
        actor=user_id or "unknown",
        actor_type="user",
        resource_type="authentication",
        resource_id=method,
        action="authenticate_failed",
        details={
            "method": method,
            "reason": reason,
            "success": False,
            **details,
        },
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )


async def audit_session_created(
    session_id: str,
    user_id: str,
    session_type: str,
    expiry: datetime | None = None,
    ip_address: str | None = None,
    **details: Any,
) -> AuditEntry:
    """
    Log session creation.

    Args:
        session_id: ID of the created session
        user_id: ID of the user
        session_type: Type of session (e.g., "jwt", "api_key")
        expiry: Session expiry time
        ip_address: Client IP address
        **details: Additional details

    Returns:
        The created audit entry
    """
    return await get_audit_log().append(
        event_type=SECURITY_EVENTS["session_created"],
        actor=user_id,
        actor_type="user",
        resource_type="session",
        resource_id=session_id,
        action="create",
        details={
            "session_type": session_type,
            "expiry": expiry.isoformat() if expiry else None,
            **details,
        },
        ip_address=ip_address,
    )


async def audit_token_issued(
    token_id: str,
    user_id: str,
    token_type: str,
    scopes: list[str] | None = None,
    expiry: datetime | None = None,
    **details: Any,
) -> AuditEntry:
    """
    Log token issuance.

    Args:
        token_id: ID or hash of the token
        user_id: ID of the user
        token_type: Type of token (e.g., "access", "refresh", "api_key")
        scopes: Granted scopes
        expiry: Token expiry time
        **details: Additional details

    Returns:
        The created audit entry
    """
    return await get_audit_log().append(
        event_type=SECURITY_EVENTS["token_issued"],
        actor=user_id,
        actor_type="user",
        resource_type="token",
        resource_id=token_id,
        action="issue",
        details={
            "token_type": token_type,
            "scopes": scopes or [],
            "expiry": expiry.isoformat() if expiry else None,
            **details,
        },
    )


# =============================================================================
# RBAC Audit Functions
# =============================================================================


async def audit_rbac_decision(
    user_id: str,
    permission: str,
    granted: bool,
    resource_type: str,
    resource_id: str,
    role: str | None = None,
    workspace_id: str | None = None,
    **details: Any,
) -> AuditEntry:
    """
    Log an RBAC authorization decision.

    Args:
        user_id: ID of the user
        permission: Permission being checked
        granted: Whether permission was granted
        resource_type: Type of resource being accessed
        resource_id: ID of the resource
        role: Role used for the decision
        workspace_id: Workspace context
        **details: Additional details

    Returns:
        The created audit entry
    """
    record_rbac_decision(permission, granted)

    event_type = SECURITY_EVENTS["rbac_granted"] if granted else SECURITY_EVENTS["rbac_denied"]

    return await get_audit_log().append(
        event_type=event_type,
        actor=user_id,
        actor_type="user",
        resource_type=resource_type,
        resource_id=resource_id,
        action="authorize",
        workspace_id=workspace_id,
        details={
            "permission": permission,
            "granted": granted,
            "role": role,
            **details,
        },
    )


async def audit_role_change(
    target_user_id: str,
    actor_id: str,
    role: str,
    action: str,
    workspace_id: str | None = None,
    **details: Any,
) -> AuditEntry:
    """
    Log a role assignment or revocation.

    Args:
        target_user_id: ID of the user whose role changed
        actor_id: ID of the user making the change
        role: Role being assigned/revoked
        action: "assign" or "revoke"
        workspace_id: Workspace context
        **details: Additional details

    Returns:
        The created audit entry
    """
    event_type = (
        SECURITY_EVENTS["role_assigned"] if action == "assign" else SECURITY_EVENTS["role_revoked"]
    )

    return await get_audit_log().append(
        event_type=event_type,
        actor=actor_id,
        actor_type="user",
        resource_type="user_role",
        resource_id=target_user_id,
        action=action,
        workspace_id=workspace_id,
        details={
            "target_user": target_user_id,
            "role": role,
            **details,
        },
    )


# =============================================================================
# Encryption Audit Functions
# =============================================================================


async def audit_encryption_operation(
    actor: str,
    operation: str,
    success: bool,
    store: str | None = None,
    field: str | None = None,
    record_id: str | None = None,
    latency_ms: float | None = None,
    **details: Any,
) -> AuditEntry:
    """
    Log an encryption or decryption operation.

    Args:
        actor: User or system performing the operation
        operation: "encrypt" or "decrypt"
        success: Whether the operation succeeded
        store: Store name if field-level encryption
        field: Field name if field-level encryption
        record_id: Record ID if applicable
        latency_ms: Operation latency in milliseconds
        **details: Additional details

    Returns:
        The created audit entry
    """
    record_encryption_operation(operation, success, (latency_ms or 0) / 1000)

    # Map operation name to event key (encrypt -> encryption, decrypt -> decryption)
    event_key_base = f"{operation}ion" if operation in ("encrypt", "decrypt") else operation
    event_type = (
        SECURITY_EVENTS[f"{event_key_base}_success"]
        if success
        else SECURITY_EVENTS[f"{event_key_base}_failure"]
    )

    return await get_audit_log().append(
        event_type=event_type,
        actor=actor,
        actor_type="system" if actor.startswith("system") else "user",
        resource_type="encryption",
        resource_id=record_id or f"{store}:{field}" if store else operation,
        action=operation,
        details={
            "success": success,
            "store": store,
            "field": field,
            "latency_ms": latency_ms,
            **details,
        },
    )


async def audit_key_rotation(
    actor: str,
    key_id: str,
    old_version: int,
    new_version: int,
    success: bool,
    latency_ms: float | None = None,
    records_re_encrypted: int = 0,
    **details: Any,
) -> AuditEntry:
    """
    Log a key rotation event.

    Args:
        actor: User or system performing the rotation
        key_id: ID of the key being rotated
        old_version: Previous key version
        new_version: New key version
        success: Whether the rotation succeeded
        latency_ms: Operation latency in milliseconds
        records_re_encrypted: Number of records re-encrypted
        **details: Additional details

    Returns:
        The created audit entry
    """
    record_key_rotation(key_id, success, (latency_ms or 0) / 1000)

    return await get_audit_log().append(
        event_type=SECURITY_EVENTS["key_rotated"],
        actor=actor,
        actor_type="system" if actor.startswith("system") else "user",
        resource_type="encryption_key",
        resource_id=key_id,
        action="rotate",
        details={
            "old_version": old_version,
            "new_version": new_version,
            "success": success,
            "latency_ms": latency_ms,
            "records_re_encrypted": records_re_encrypted,
            **details,
        },
    )


async def audit_key_generated(
    actor: str,
    key_id: str,
    key_type: str,
    **details: Any,
) -> AuditEntry:
    """
    Log key generation.

    Args:
        actor: User or system generating the key
        key_id: ID of the generated key
        key_type: Type of key (e.g., "master", "session", "ephemeral")
        **details: Additional details

    Returns:
        The created audit entry
    """
    return await get_audit_log().append(
        event_type=SECURITY_EVENTS["key_generated"],
        actor=actor,
        actor_type="system" if actor.startswith("system") else "user",
        resource_type="encryption_key",
        resource_id=key_id,
        action="generate",
        details={
            "key_type": key_type,
            **details,
        },
    )


# =============================================================================
# Secret Access Audit Functions
# =============================================================================


async def audit_secret_access(
    actor: str,
    secret_type: str,
    store: str,
    operation: str,
    secret_id: str | None = None,
    workspace_id: str | None = None,
    **details: Any,
) -> AuditEntry:
    """
    Log secret access.

    Args:
        actor: User or system accessing the secret
        secret_type: Type of secret (e.g., "api_key", "oauth_token")
        store: Store containing the secret
        operation: Operation performed (e.g., "read", "decrypt")
        secret_id: ID of the secret (if applicable)
        workspace_id: Workspace context
        **details: Additional details

    Returns:
        The created audit entry
    """
    record_secret_access(secret_type, operation)

    return await get_audit_log().append(
        event_type=SECURITY_EVENTS["secret_accessed"],
        actor=actor,
        actor_type="system" if actor.startswith("system") else "user",
        resource_type="secret",
        resource_id=secret_id or f"{store}:{secret_type}",
        action=operation,
        workspace_id=workspace_id,
        details={
            "secret_type": secret_type,
            "store": store,
            **details,
        },
    )


async def audit_secret_modified(
    actor: str,
    secret_type: str,
    store: str,
    action: str,
    secret_id: str,
    workspace_id: str | None = None,
    **details: Any,
) -> AuditEntry:
    """
    Log secret creation, update, or deletion.

    Args:
        actor: User or system modifying the secret
        secret_type: Type of secret
        store: Store containing the secret
        action: "create", "update", or "delete"
        secret_id: ID of the secret
        workspace_id: Workspace context
        **details: Additional details

    Returns:
        The created audit entry
    """
    event_map = {
        "create": SECURITY_EVENTS["secret_created"],
        "update": SECURITY_EVENTS["secret_updated"],
        "delete": SECURITY_EVENTS["secret_deleted"],
    }
    event_type = event_map.get(action, SECURITY_EVENTS["secret_updated"])

    return await get_audit_log().append(
        event_type=event_type,
        actor=actor,
        actor_type="system" if actor.startswith("system") else "user",
        resource_type="secret",
        resource_id=secret_id,
        action=action,
        workspace_id=workspace_id,
        details={
            "secret_type": secret_type,
            "store": store,
            **details,
        },
    )


# =============================================================================
# Migration Audit Functions
# =============================================================================


async def audit_migration_started(
    actor: str,
    migration_type: str,
    stores: list[str],
    dry_run: bool = False,
    **details: Any,
) -> AuditEntry:
    """
    Log the start of a data migration.

    Args:
        actor: User or system starting the migration
        migration_type: Type of migration (e.g., "encrypt_secrets")
        stores: Stores being migrated
        dry_run: Whether this is a dry run
        **details: Additional details

    Returns:
        The created audit entry
    """
    return await get_audit_log().append(
        event_type=SECURITY_EVENTS["migration_started"],
        actor=actor,
        actor_type="system" if actor.startswith("system") else "user",
        resource_type="migration",
        resource_id=migration_type,
        action="start",
        details={
            "migration_type": migration_type,
            "stores": stores,
            "dry_run": dry_run,
            "started_at": datetime.now(timezone.utc).isoformat(),
            **details,
        },
    )


async def audit_migration_completed(
    actor: str,
    migration_type: str,
    success: bool,
    records_migrated: int,
    errors: list[str],
    duration_seconds: float,
    **details: Any,
) -> AuditEntry:
    """
    Log the completion of a data migration.

    Args:
        actor: User or system that ran the migration
        migration_type: Type of migration
        success: Whether the migration succeeded
        records_migrated: Number of records migrated
        errors: List of errors encountered
        duration_seconds: Total duration in seconds
        **details: Additional details

    Returns:
        The created audit entry
    """
    return await get_audit_log().append(
        event_type=SECURITY_EVENTS["migration_completed"],
        actor=actor,
        actor_type="system" if actor.startswith("system") else "user",
        resource_type="migration",
        resource_id=migration_type,
        action="complete",
        details={
            "migration_type": migration_type,
            "success": success,
            "records_migrated": records_migrated,
            "error_count": len(errors),
            "errors": errors[:10],  # Limit errors in audit log
            "duration_seconds": duration_seconds,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            **details,
        },
    )


# =============================================================================
# Security Incident Audit Functions
# =============================================================================


async def audit_security_incident(
    severity: str,
    incident_type: str,
    description: str,
    actor: str | None = None,
    ip_address: str | None = None,
    affected_resources: list[dict[str, str]] | None = None,
    **details: Any,
) -> AuditEntry:
    """
    Log a security incident.

    Args:
        severity: "critical", "high", "medium", "low"
        incident_type: Type of incident (e.g., "unauthorized_access", "brute_force")
        description: Human-readable description
        actor: User or system involved (if known)
        ip_address: Source IP address
        affected_resources: List of affected resources
        **details: Additional details

    Returns:
        The created audit entry
    """
    record_security_incident(severity, incident_type)

    return await get_audit_log().append(
        event_type=SECURITY_EVENTS["incident_detected"],
        actor=actor or "system",
        actor_type="system",
        resource_type="security_incident",
        resource_id=f"{incident_type}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        action="detect",
        ip_address=ip_address,
        details={
            "severity": severity,
            "incident_type": incident_type,
            "description": description,
            "affected_resources": affected_resources or [],
            "detected_at": datetime.now(timezone.utc).isoformat(),
            **details,
        },
    )


async def audit_security_alert(
    alert_type: str,
    destination: str,
    triggered_by: str,
    severity: str,
    **details: Any,
) -> AuditEntry:
    """
    Log a security alert being sent.

    Args:
        alert_type: Type of alert
        destination: Where the alert was sent (e.g., "siem", "email", "slack")
        triggered_by: What triggered the alert
        severity: Alert severity
        **details: Additional details

    Returns:
        The created audit entry
    """
    record_security_alert(alert_type, destination)

    return await get_audit_log().append(
        event_type=SECURITY_EVENTS["alert_triggered"],
        actor="system",
        actor_type="system",
        resource_type="security_alert",
        resource_id=alert_type,
        action="send",
        details={
            "alert_type": alert_type,
            "destination": destination,
            "triggered_by": triggered_by,
            "severity": severity,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            **details,
        },
    )


async def audit_request_blocked(
    reason: str,
    ip_address: str,
    user_id: str | None = None,
    path: str | None = None,
    method: str | None = None,
    user_agent: str | None = None,
    **details: Any,
) -> AuditEntry:
    """
    Log a blocked request.

    Args:
        reason: Reason for blocking (e.g., "rate_limit", "unauthorized")
        ip_address: Source IP address
        user_id: User ID if known
        path: Request path
        method: HTTP method
        user_agent: Client user agent
        **details: Additional details

    Returns:
        The created audit entry
    """
    record_blocked_request(reason, ip_address)

    return await get_audit_log().append(
        event_type=SECURITY_EVENTS["request_blocked"],
        actor=user_id or ip_address,
        actor_type="user" if user_id else "unknown",
        resource_type="request",
        resource_id=f"{method}:{path}" if path else reason,
        action="block",
        ip_address=ip_address,
        user_agent=user_agent,
        details={
            "reason": reason,
            "path": path,
            "method": method,
            "blocked_at": datetime.now(timezone.utc).isoformat(),
            **details,
        },
    )


# =============================================================================
# Query Functions
# =============================================================================


async def get_security_events(
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    event_types: list[str] | None = None,
    actors: list[str] | None = None,
    workspace_id: str | None = None,
    severity: str | None = None,
    limit: int = 100,
) -> list[AuditEntry]:
    """
    Query security-related audit events.

    Args:
        start_time: Start of time range
        end_time: End of time range
        event_types: Specific security event types to filter
        actors: Filter by actors
        workspace_id: Filter by workspace
        severity: Filter by severity (for incidents)
        limit: Maximum entries to return

    Returns:
        List of matching audit entries
    """
    # Convert friendly event names to full event types
    if event_types:
        event_types = [SECURITY_EVENTS.get(et, et) for et in event_types]
    else:
        # Default to all security events
        event_types = list(SECURITY_EVENTS.values())

    entries = await get_audit_log().query(
        start_time=start_time,
        end_time=end_time,
        event_types=event_types,
        actors=actors,
        workspace_id=workspace_id,
        limit=limit,
    )

    # Filter by severity if specified
    if severity:
        entries = [e for e in entries if e.details.get("severity") == severity]

    return entries


async def get_auth_failures(
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    ip_address: str | None = None,
    limit: int = 100,
) -> list[AuditEntry]:
    """
    Get authentication failures.

    Args:
        start_time: Start of time range
        end_time: End of time range
        ip_address: Filter by IP address
        limit: Maximum entries to return

    Returns:
        List of auth failure audit entries
    """
    entries = await get_audit_log().query(
        start_time=start_time,
        end_time=end_time,
        event_types=[SECURITY_EVENTS["auth_failure"]],
        limit=limit,
    )

    if ip_address:
        entries = [e for e in entries if e.ip_address == ip_address]

    return entries


async def get_security_incidents(
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    severity: str | None = None,
    limit: int = 100,
) -> list[AuditEntry]:
    """
    Get security incidents.

    Args:
        start_time: Start of time range
        end_time: End of time range
        severity: Filter by severity
        limit: Maximum entries to return

    Returns:
        List of security incident audit entries
    """
    incident_events = [
        SECURITY_EVENTS["incident_detected"],
        SECURITY_EVENTS["incident_escalated"],
        SECURITY_EVENTS["incident_resolved"],
    ]

    entries = await get_audit_log().query(
        start_time=start_time,
        end_time=end_time,
        event_types=incident_events,
        limit=limit,
    )

    if severity:
        entries = [e for e in entries if e.details.get("severity") == severity]

    return entries
