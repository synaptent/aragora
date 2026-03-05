"""
RBAC Audit Logging - Track authorization decisions for compliance.

Provides comprehensive logging of all authorization decisions,
role changes, and permission modifications for audit trails.

Features:
- In-memory buffering for high-throughput logging
- Persistent storage to PostgreSQL/SQLite for compliance
- HMAC-SHA256 event signing for integrity verification
- SOC2 Type II compliant audit trails
- Break-glass event tracking with tamper detection

Usage:
    from aragora.rbac.audit import (
        get_auditor,
        PersistentAuditHandler,
        verify_event_signature,
    )

    # Enable persistent audit logging
    auditor = get_auditor()
    handler = PersistentAuditHandler()
    auditor.add_handler(handler.handle_event)

    # Verify event integrity
    is_valid = verify_event_signature(event, signature)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from collections.abc import Callable
from uuid import uuid4

from .models import AuthorizationDecision, RoleAssignment

logger = logging.getLogger(__name__)

# HMAC signing key - should be set via environment variable in production
_AUDIT_SIGNING_KEY: bytes | None = None
_signing_key_lock = threading.Lock()


def get_audit_signing_key() -> bytes:
    """
    Get or generate the HMAC signing key for audit events.

    The key is loaded from ARAGORA_AUDIT_SIGNING_KEY environment variable.
    If not set in production/staging, raises an error.
    For development, generates a random key if not set.

    Returns:
        32-byte HMAC signing key

    Raises:
        RuntimeError: If key not set in production/staging environment
    """
    global _AUDIT_SIGNING_KEY
    with _signing_key_lock:
        if _AUDIT_SIGNING_KEY is None:
            key_hex = os.environ.get("ARAGORA_AUDIT_SIGNING_KEY")
            if key_hex:
                try:
                    _AUDIT_SIGNING_KEY = bytes.fromhex(key_hex)
                    if len(_AUDIT_SIGNING_KEY) < 32:
                        raise ValueError("Key must be at least 32 bytes (64 hex chars)")
                    logger.debug("Loaded audit signing key from environment")
                except ValueError as e:
                    raise RuntimeError(
                        f"Invalid ARAGORA_AUDIT_SIGNING_KEY format: {e}. "
                        "Key must be a hex-encoded string of at least 64 characters "
                        "(32 bytes). Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
                    ) from e
            else:
                env = os.environ.get("ARAGORA_ENV", "development")
                if env in ("production", "prod", "staging"):
                    # SECURITY: Require explicit key in production to ensure
                    # audit trail integrity across process restarts
                    raise RuntimeError(
                        f"ARAGORA_AUDIT_SIGNING_KEY required in {env} environment. "
                        "Audit event signatures cannot be verified without a persistent key. "
                        "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
                    )
                else:
                    # Generate random key for development only
                    _AUDIT_SIGNING_KEY = secrets.token_bytes(32)
                    logger.debug("Generated ephemeral audit signing key for development")
        return _AUDIT_SIGNING_KEY


def set_audit_signing_key(key: bytes) -> None:
    """
    Set the HMAC signing key for audit events.

    Args:
        key: 32-byte HMAC signing key
    """
    global _AUDIT_SIGNING_KEY
    if len(key) < 32:
        raise ValueError("Audit signing key must be at least 32 bytes")
    with _signing_key_lock:
        _AUDIT_SIGNING_KEY = key


def compute_event_signature(event_data: dict[str, Any]) -> str:
    """
    Compute HMAC-SHA256 signature for an audit event.

    Args:
        event_data: Event dictionary to sign (without signature field)

    Returns:
        Hex-encoded HMAC-SHA256 signature
    """
    # Remove signature from data if present (for verification)
    data_to_sign = {k: v for k, v in event_data.items() if k != "signature"}
    # Serialize deterministically
    canonical = json.dumps(data_to_sign, sort_keys=True, separators=(",", ":"))
    key = get_audit_signing_key()
    signature = hmac.new(key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return signature


def verify_event_signature(event_data: dict[str, Any], signature: str) -> bool:
    """
    Verify HMAC-SHA256 signature for an audit event.

    Args:
        event_data: Event dictionary to verify
        signature: Expected hex-encoded signature

    Returns:
        True if signature is valid
    """
    computed = compute_event_signature(event_data)
    return hmac.compare_digest(computed, signature)


class AuditEventType(str, Enum):
    """Types of authorization audit events."""

    # Permission checks
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_DENIED = "permission_denied"

    # Role management
    ROLE_ASSIGNED = "role_assigned"
    ROLE_REVOKED = "role_revoked"
    ROLE_CREATED = "role_created"
    ROLE_DELETED = "role_deleted"
    ROLE_MODIFIED = "role_modified"

    # Session events
    SESSION_CREATED = "session_created"
    SESSION_EXPIRED = "session_expired"
    SESSION_REVOKED = "session_revoked"

    # API key events
    API_KEY_CREATED = "api_key_created"
    API_KEY_REVOKED = "api_key_revoked"
    API_KEY_USED = "api_key_used"

    # Admin actions
    IMPERSONATION_START = "impersonation_start"
    IMPERSONATION_END = "impersonation_end"
    POLICY_CHANGED = "policy_changed"

    # Break-glass / Emergency access
    BREAK_GLASS_ACTIVATED = "break_glass_activated"
    BREAK_GLASS_DEACTIVATED = "break_glass_deactivated"
    BREAK_GLASS_ACTION = "break_glass_action"

    # Approval workflow
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    APPROVAL_EXPIRED = "approval_expired"

    # Generic custom event
    CUSTOM = "custom"


@dataclass
class AuditEvent:
    """
    Audit event for authorization-related actions.

    Attributes:
        id: Unique event identifier
        event_type: Type of authorization event
        timestamp: When the event occurred
        user_id: User who performed or was subject to the action
        org_id: Organization context
        actor_id: User who initiated the action (may differ from user_id)
        resource_type: Type of resource involved
        resource_id: Specific resource ID
        permission_key: Permission that was checked/modified
        decision: Outcome (allowed/denied)
        reason: Explanation for the decision
        ip_address: Request IP address
        user_agent: Request user agent
        request_id: Request trace ID
        metadata: Additional event data
        signature: HMAC-SHA256 signature for integrity verification
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    event_type: AuditEventType = AuditEventType.PERMISSION_GRANTED
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    user_id: str | None = None
    org_id: str | None = None
    actor_id: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    permission_key: str | None = None
    decision: bool = True
    reason: str = ""
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    signature: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "user_id": self.user_id,
            "org_id": self.org_id,
            "actor_id": self.actor_id,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "permission_key": self.permission_key,
            "decision": self.decision,
            "reason": self.reason,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "request_id": self.request_id,
            "metadata": self.metadata,
        }

    def to_signed_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary with HMAC-SHA256 signature.

        The signature covers all event fields to ensure integrity.
        Use verify_event_signature() to validate.

        Returns:
            Event dictionary with 'signature' field appended
        """
        data = self.to_dict()
        data["signature"] = compute_event_signature(data)
        self.signature = data["signature"]
        return data

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())

    def verify_signature(self) -> bool:
        """
        Verify the event's signature.

        Returns:
            True if signature is valid, False otherwise
        """
        if not self.signature:
            return False
        return verify_event_signature(self.to_dict(), self.signature)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditEvent:
        """
        Create an AuditEvent from a dictionary.

        Args:
            data: Event dictionary (from to_dict() or database)

        Returns:
            AuditEvent instance
        """
        # Parse timestamp
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        elif timestamp is None:
            timestamp = datetime.now(timezone.utc)

        # Parse event type
        event_type = data.get("event_type", "permission_granted")
        if isinstance(event_type, str):
            try:
                event_type = AuditEventType(event_type)
            except ValueError:
                event_type = AuditEventType.CUSTOM

        return cls(
            id=data.get("id", str(uuid4())),
            event_type=event_type,
            timestamp=timestamp,
            user_id=data.get("user_id"),
            org_id=data.get("org_id"),
            actor_id=data.get("actor_id"),
            resource_type=data.get("resource_type"),
            resource_id=data.get("resource_id"),
            permission_key=data.get("permission_key"),
            decision=data.get("decision", True),
            reason=data.get("reason", ""),
            ip_address=data.get("ip_address"),
            user_agent=data.get("user_agent"),
            request_id=data.get("request_id"),
            metadata=data.get("metadata", {}),
            signature=data.get("signature"),
        )


class AuthorizationAuditor:
    """
    Auditor for authorization events.

    Logs all authorization decisions and role changes for compliance
    and security monitoring.
    """

    def __init__(
        self,
        handlers: list[Callable[[AuditEvent], None]] | None = None,
        log_denied_only: bool = False,
        include_cached: bool = False,
    ) -> None:
        """
        Initialize the auditor.

        Args:
            handlers: List of handler functions to process events
            log_denied_only: If True, only log denied decisions
            include_cached: If True, also log cached decisions
        """
        self._handlers = handlers or []
        self._log_denied_only = log_denied_only
        self._include_cached = include_cached
        self._event_buffer: list[AuditEvent] = []
        self._buffer_size = 100

        # Add default logger handler
        self._handlers.append(self._default_log_handler)

    def log_decision(self, decision: AuthorizationDecision) -> None:
        """
        Log an authorization decision.

        Args:
            decision: The authorization decision to log
        """
        # Skip cached decisions unless configured to include
        if decision.cached and not self._include_cached:
            return

        # Skip allowed decisions if log_denied_only
        if decision.allowed and self._log_denied_only:
            return

        event = AuditEvent(
            event_type=(
                AuditEventType.PERMISSION_GRANTED
                if decision.allowed
                else AuditEventType.PERMISSION_DENIED
            ),
            timestamp=decision.checked_at,
            user_id=decision.context.user_id if decision.context else None,
            org_id=decision.context.org_id if decision.context else None,
            permission_key=decision.permission_key,
            resource_id=decision.resource_id,
            decision=decision.allowed,
            reason=decision.reason,
            ip_address=decision.context.ip_address if decision.context else None,
            user_agent=decision.context.user_agent if decision.context else None,
            request_id=decision.context.request_id if decision.context else None,
        )

        self._emit_event(event)

    def log_role_assignment(
        self,
        assignment: RoleAssignment,
        actor_id: str,
        ip_address: str | None = None,
    ) -> None:
        """Log a role assignment."""
        event = AuditEvent(
            event_type=AuditEventType.ROLE_ASSIGNED,
            user_id=assignment.user_id,
            org_id=assignment.org_id,
            actor_id=actor_id,
            resource_type="role",
            resource_id=assignment.role_id,
            decision=True,
            reason=f"Role '{assignment.role_id}' assigned to user",
            ip_address=ip_address,
            metadata={
                "assignment_id": assignment.id,
                "expires_at": assignment.expires_at.isoformat() if assignment.expires_at else None,
            },
        )

        self._emit_event(event)

    def log_role_revocation(
        self,
        user_id: str,
        role_id: str,
        org_id: str | None,
        actor_id: str,
        reason: str = "",
        ip_address: str | None = None,
    ) -> None:
        """Log a role revocation."""
        event = AuditEvent(
            event_type=AuditEventType.ROLE_REVOKED,
            user_id=user_id,
            org_id=org_id,
            actor_id=actor_id,
            resource_type="role",
            resource_id=role_id,
            decision=True,
            reason=reason or f"Role '{role_id}' revoked from user",
            ip_address=ip_address,
        )

        self._emit_event(event)

    def log_api_key_created(
        self,
        user_id: str,
        key_id: str,
        scopes: set[str],
        actor_id: str | None = None,
        ip_address: str | None = None,
    ) -> None:
        """Log API key creation."""
        event = AuditEvent(
            event_type=AuditEventType.API_KEY_CREATED,
            user_id=user_id,
            actor_id=actor_id or user_id,
            resource_type="api_key",
            resource_id=key_id,
            decision=True,
            reason="API key created",
            ip_address=ip_address,
            metadata={
                "scopes": list(scopes),
            },
        )

        self._emit_event(event)

    def log_api_key_revoked(
        self,
        user_id: str,
        key_id: str,
        actor_id: str,
        reason: str = "",
        ip_address: str | None = None,
    ) -> None:
        """Log API key revocation."""
        event = AuditEvent(
            event_type=AuditEventType.API_KEY_REVOKED,
            user_id=user_id,
            actor_id=actor_id,
            resource_type="api_key",
            resource_id=key_id,
            decision=True,
            reason=reason or "API key revoked",
            ip_address=ip_address,
        )

        self._emit_event(event)

    def log_impersonation_start(
        self,
        actor_id: str,
        target_user_id: str,
        org_id: str | None,
        reason: str,
        ip_address: str | None = None,
    ) -> None:
        """Log start of user impersonation."""
        event = AuditEvent(
            event_type=AuditEventType.IMPERSONATION_START,
            user_id=target_user_id,
            org_id=org_id,
            actor_id=actor_id,
            decision=True,
            reason=reason,
            ip_address=ip_address,
        )

        self._emit_event(event)

    def log_impersonation_end(
        self,
        actor_id: str,
        target_user_id: str,
        org_id: str | None,
        ip_address: str | None = None,
    ) -> None:
        """Log end of user impersonation."""
        event = AuditEvent(
            event_type=AuditEventType.IMPERSONATION_END,
            user_id=target_user_id,
            org_id=org_id,
            actor_id=actor_id,
            decision=True,
            reason="Impersonation session ended",
            ip_address=ip_address,
        )

        self._emit_event(event)

    def log_session_event(
        self,
        event_type: AuditEventType,
        user_id: str,
        session_id: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        reason: str = "",
    ) -> None:
        """Log session-related events."""
        event = AuditEvent(
            event_type=event_type,
            user_id=user_id,
            resource_type="session",
            resource_id=session_id,
            decision=True,
            reason=reason,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        self._emit_event(event)

    async def log_event(
        self,
        event_type: str,
        details: dict[str, Any] | None = None,
        category: str | None = None,
        user_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> None:
        """
        Log a generic audit event.

        This is a flexible method for logging custom or specialized events
        like break-glass access, approval workflows, etc.

        Args:
            event_type: Event type string (will try to match AuditEventType enum)
            details: Optional event details/metadata
            category: Optional event category (e.g., "break_glass", "approval")
            user_id: Optional user ID associated with the event
            resource_type: Optional resource type
            resource_id: Optional resource ID
        """
        # Try to match event_type to enum, fallback to CUSTOM
        try:
            audit_event_type = AuditEventType(event_type)
        except ValueError:
            audit_event_type = AuditEventType.CUSTOM

        event = AuditEvent(
            event_type=audit_event_type,
            user_id=user_id or "system",
            resource_type=resource_type or category or "unknown",
            resource_id=resource_id or "",
            decision=True,
            reason=event_type if audit_event_type == AuditEventType.CUSTOM else "",
            metadata=details or {},
        )

        self._emit_event(event)

    def add_handler(self, handler: Callable[[AuditEvent], None]) -> None:
        """Add an event handler."""
        self._handlers.append(handler)

    def remove_handler(self, handler: Callable[[AuditEvent], None]) -> None:
        """Remove an event handler."""
        if handler in self._handlers:
            self._handlers.remove(handler)

    def flush_buffer(self) -> list[AuditEvent]:
        """Flush and return buffered events."""
        events = self._event_buffer.copy()
        self._event_buffer.clear()
        return events

    def _emit_event(self, event: AuditEvent) -> None:
        """Emit event to all handlers."""
        for handler in self._handlers:
            try:
                handler(event)
            except (
                OSError,
                ValueError,
                TypeError,
                RuntimeError,
                AttributeError,
                KeyError,
                ConnectionError,
                TimeoutError,
                PermissionError,
            ) as e:
                logger.error("Error in audit handler: %s", e)
                # Continue to next handler
            except Exception as e:  # noqa: BLE001 - catch-all ensures all audit handlers run even if one fails unexpectedly
                logger.error("Unexpected error in audit handler: %s", e)

        # Buffer for batch processing
        self._event_buffer.append(event)
        if len(self._event_buffer) >= self._buffer_size:
            self._event_buffer = self._event_buffer[-self._buffer_size :]

    def _default_log_handler(self, event: AuditEvent) -> None:
        """Default handler that logs to Python logger."""
        log_level = logging.INFO if event.decision else logging.WARNING

        logger.log(
            log_level,
            "RBAC Audit: %s | user=%s | org=%s | permission=%s | resource=%s | decision=%s | reason=%s",
            event.event_type.value,
            event.user_id,
            event.org_id,
            event.permission_key,
            event.resource_id,
            event.decision,
            event.reason,
            extra={
                "audit_event": event.to_dict(),
            },
        )


# Global auditor instance
_auditor: AuthorizationAuditor | None = None


def get_auditor() -> AuthorizationAuditor:
    """Get or create the global auditor instance."""
    global _auditor
    if _auditor is None:
        _auditor = AuthorizationAuditor()
    return _auditor


def set_auditor(auditor: AuthorizationAuditor) -> None:
    """Set the global auditor instance."""
    global _auditor
    _auditor = auditor


# Convenience functions
def log_permission_check(
    user_id: str,
    permission_key: str,
    allowed: bool,
    reason: str = "",
    resource_id: str | None = None,
    org_id: str | None = None,
    ip_address: str | None = None,
) -> None:
    """Quick function to log a permission check."""
    event = AuditEvent(
        event_type=(
            AuditEventType.PERMISSION_GRANTED if allowed else AuditEventType.PERMISSION_DENIED
        ),
        user_id=user_id,
        org_id=org_id,
        permission_key=permission_key,
        resource_id=resource_id,
        decision=allowed,
        reason=reason,
        ip_address=ip_address,
    )
    get_auditor()._emit_event(event)


# =============================================================================
# Persistent Audit Storage
# =============================================================================


class PersistentAuditHandler:
    """
    Handler that persists audit events to database storage.

    This handler integrates with the AuthorizationAuditor to provide
    SOC2 Type II compliant persistent audit trails with integrity verification.

    Features:
    - Writes to PostgreSQL or SQLite via AuditStore
    - Signs events with HMAC-SHA256 before storage
    - Supports querying and verification of historical events
    - Batch writing for high-throughput scenarios

    Usage:
        from aragora.rbac.audit import get_auditor, PersistentAuditHandler

        # Create and attach handler
        handler = PersistentAuditHandler()
        auditor = get_auditor()
        auditor.add_handler(handler.handle_event)

        # Query persisted events
        events = handler.get_events(
            user_id="user-123",
            since=datetime.now() - timedelta(days=7)
        )

        # Verify event integrity
        for event in events:
            if not event.verify_signature():
                logger.warning("Event %s has invalid signature!", event.id)
    """

    def __init__(
        self,
        store: Any | None = None,
        sign_events: bool = True,
        batch_size: int = 100,
        flush_interval_seconds: float = 5.0,
    ) -> None:
        """
        Initialize the persistent audit handler.

        Args:
            store: Optional AuditStore instance. If None, uses get_audit_store()
            sign_events: If True, sign events before storage (default: True)
            batch_size: Number of events to batch before writing (default: 100)
            flush_interval_seconds: Max time before flushing batch (default: 5.0)
        """
        self._store = store
        self._sign_events = sign_events
        self._batch_size = batch_size
        self._flush_interval = flush_interval_seconds

        # Batch buffer
        self._batch: list[AuditEvent] = []
        self._batch_lock = threading.Lock()
        self._last_flush = datetime.now(timezone.utc)

        # Statistics
        self._events_written = 0
        self._events_failed = 0

    @property
    def store(self) -> Any:
        """Get the underlying AuditStore (lazy initialization)."""
        if self._store is None:
            from aragora.storage.audit_store import get_audit_store

            self._store = get_audit_store()
        return self._store

    def handle_event(self, event: AuditEvent) -> None:
        """
        Handle an audit event by persisting it to storage.

        This method is designed to be registered with AuthorizationAuditor.add_handler().

        Args:
            event: The audit event to persist
        """
        with self._batch_lock:
            self._batch.append(event)

            # Check if we should flush
            should_flush = len(self._batch) >= self._batch_size
            time_elapsed = (datetime.now(timezone.utc) - self._last_flush).total_seconds()
            if should_flush or time_elapsed >= self._flush_interval:
                self._flush_batch()

    def _flush_batch(self) -> None:
        """Flush the event batch to storage."""
        if not self._batch:
            return

        events_to_write = self._batch.copy()
        self._batch.clear()
        self._last_flush = datetime.now(timezone.utc)

        for event in events_to_write:
            try:
                self._write_event(event)
                self._events_written += 1
            except (OSError, ValueError, TypeError, RuntimeError) as e:
                self._events_failed += 1
                logger.error("Failed to persist audit event %s: %s", event.id, e)

    def _write_event(self, event: AuditEvent) -> None:
        """Write a single event to storage."""
        # Sign the event if configured
        if self._sign_events:
            event_data = event.to_signed_dict()
        else:
            event_data = event.to_dict()

        # Map AuditEvent fields to AuditStore.log_event() parameters
        self.store.log_event(
            action=event_data["event_type"],
            resource_type=event_data.get("resource_type") or "authorization",
            resource_id=event_data.get("resource_id"),
            user_id=event_data.get("user_id"),
            org_id=event_data.get("org_id"),
            metadata={
                "event_id": event_data["id"],
                "actor_id": event_data.get("actor_id"),
                "permission_key": event_data.get("permission_key"),
                "decision": event_data["decision"],
                "reason": event_data.get("reason"),
                "request_id": event_data.get("request_id"),
                "signature": event_data.get("signature"),
                **event_data.get("metadata", {}),
            },
            ip_address=event_data.get("ip_address"),
            user_agent=event_data.get("user_agent"),
        )

    def flush(self) -> None:
        """Force flush any pending events to storage."""
        with self._batch_lock:
            self._flush_batch()

    def get_events(
        self,
        user_id: str | None = None,
        org_id: str | None = None,
        event_type: str | AuditEventType | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
        verify_signatures: bool = True,
    ) -> list[AuditEvent]:
        """
        Query persisted audit events.

        Args:
            user_id: Filter by user ID
            org_id: Filter by organization ID
            event_type: Filter by event type
            since: Filter events after this time
            until: Filter events before this time
            limit: Maximum events to return
            offset: Pagination offset
            verify_signatures: If True, verify signatures and mark invalid events

        Returns:
            List of AuditEvent instances
        """
        # Map event_type to action filter
        action = None
        if event_type:
            if isinstance(event_type, AuditEventType):
                action = event_type.value
            else:
                action = event_type

        # Query from store
        rows = self.store.get_log(
            user_id=user_id,
            org_id=org_id,
            action=action,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )

        events = []
        for row in rows:
            # Reconstruct AuditEvent from stored data
            metadata = row.get("metadata", {})
            event_data = {
                "id": metadata.get("event_id", row.get("id")),
                "event_type": row.get("action", "custom"),
                "timestamp": row.get("timestamp"),
                "user_id": row.get("user_id"),
                "org_id": row.get("org_id"),
                "actor_id": metadata.get("actor_id"),
                "resource_type": row.get("resource_type"),
                "resource_id": row.get("resource_id"),
                "permission_key": metadata.get("permission_key"),
                "decision": metadata.get("decision", True),
                "reason": metadata.get("reason", ""),
                "ip_address": row.get("ip_address"),
                "user_agent": row.get("user_agent"),
                "request_id": metadata.get("request_id"),
                "metadata": {
                    k: v
                    for k, v in metadata.items()
                    if k
                    not in (
                        "event_id",
                        "actor_id",
                        "permission_key",
                        "decision",
                        "reason",
                        "request_id",
                        "signature",
                    )
                },
                "signature": metadata.get("signature"),
            }

            event = AuditEvent.from_dict(event_data)

            # Verify signature if requested
            if verify_signatures and event.signature:
                if not event.verify_signature():
                    logger.warning(
                        "Audit event %s has invalid signature - possible tampering",
                        event.id,
                    )
                    # Mark in metadata that signature verification failed
                    event.metadata["_signature_valid"] = False
                else:
                    event.metadata["_signature_valid"] = True

            events.append(event)

        return events

    def get_break_glass_events(
        self,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """
        Get break-glass/emergency access events.

        Args:
            since: Filter events after this time
            limit: Maximum events to return

        Returns:
            List of break-glass related AuditEvent instances
        """
        all_events = []
        for event_type in [
            AuditEventType.BREAK_GLASS_ACTIVATED,
            AuditEventType.BREAK_GLASS_DEACTIVATED,
            AuditEventType.BREAK_GLASS_ACTION,
        ]:
            events = self.get_events(
                event_type=event_type,
                since=since,
                limit=limit,
            )
            all_events.extend(events)

        # Sort by timestamp descending
        all_events.sort(key=lambda e: e.timestamp, reverse=True)
        return all_events[:limit]

    def get_event_count(
        self,
        user_id: str | None = None,
        org_id: str | None = None,
        event_type: str | AuditEventType | None = None,
    ) -> int:
        """
        Get count of persisted audit events.

        Args:
            user_id: Filter by user ID
            org_id: Filter by organization ID
            event_type: Filter by event type

        Returns:
            Total count of matching events
        """
        action = None
        if event_type:
            if isinstance(event_type, AuditEventType):
                action = event_type.value
            else:
                action = event_type

        return self.store.get_log_count(
            user_id=user_id,
            org_id=org_id,
            action=action,
        )

    def get_stats(self) -> dict[str, Any]:
        """
        Get handler statistics.

        Returns:
            Dictionary with events_written, events_failed, pending_count
        """
        with self._batch_lock:
            pending = len(self._batch)

        return {
            "events_written": self._events_written,
            "events_failed": self._events_failed,
            "pending_count": pending,
            "sign_events": self._sign_events,
            "batch_size": self._batch_size,
        }

    def close(self) -> None:
        """Flush pending events and close the handler."""
        self.flush()


# Module-level persistent handler singleton
_persistent_handler: PersistentAuditHandler | None = None
_handler_lock = threading.Lock()


def get_persistent_handler() -> PersistentAuditHandler:
    """
    Get or create the global persistent audit handler.

    Returns:
        PersistentAuditHandler singleton instance
    """
    global _persistent_handler
    if _persistent_handler is None:
        with _handler_lock:
            if _persistent_handler is None:
                _persistent_handler = PersistentAuditHandler()
    return _persistent_handler


def set_persistent_handler(handler: PersistentAuditHandler) -> None:
    """Set the global persistent audit handler."""
    global _persistent_handler
    with _handler_lock:
        _persistent_handler = handler


def enable_persistent_auditing() -> PersistentAuditHandler:
    """
    Enable persistent audit logging.

    Attaches the PersistentAuditHandler to the global auditor.

    Returns:
        The PersistentAuditHandler instance

    Example:
        from aragora.rbac.audit import enable_persistent_auditing

        # Enable at application startup
        handler = enable_persistent_auditing()

        # Query events later
        events = handler.get_events(user_id="user-123")
    """
    handler = get_persistent_handler()
    auditor = get_auditor()
    auditor.add_handler(handler.handle_event)
    logger.info("Persistent RBAC audit logging enabled")
    return handler


# =============================================================================
# Endpoint Coverage Scan
# =============================================================================


def compute_endpoint_coverage() -> dict[str, Any]:
    """
    Scan handler modules and count endpoints decorated with @require_permission.

    Uses grep-based introspection of the handler source tree to count:
    - total_endpoints: all ``async def handle`` / ``async def _handle_*`` methods
      across handler modules.
    - covered_endpoints: those that reference ``require_permission`` in their
      source (either as a decorator or via a direct call).

    Returns a dict with keys:
        covered_endpoints (int): number of endpoints with RBAC decoration.
        total_endpoints (int): total endpoints found.
        coverage_pct (float): percentage covered, 0.0–100.0.

    This function never raises — it returns zeros on scan failure.
    """
    import pathlib
    import re

    handlers_root = pathlib.Path(__file__).parent.parent / "server" / "handlers"
    if not handlers_root.is_dir():
        return {"covered_endpoints": 0, "total_endpoints": 0, "coverage_pct": 0.0}

    total = 0
    covered = 0

    # Pattern for async handler methods (handle, _handle_*, _get_*, _post_*, etc.)
    method_pattern = re.compile(
        r"^\s+(?:@[^\n]+\n\s+)*async\s+def\s+(?:handle|_handle_|_get_|_post_|_put_|_patch_|_delete_|_list_|_create_|_update_)",
        re.MULTILINE,
    )
    require_pattern = re.compile(r"require_permission\s*\(")

    try:
        for py_file in handlers_root.rglob("*.py"):
            # Skip test files, __pycache__, and __init__
            if any(p in py_file.parts for p in ("__pycache__", "tests")):
                continue
            if py_file.name.startswith("__"):
                continue

            try:
                source = py_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            # Find all async handler methods in this file
            for match in method_pattern.finditer(source):
                total += 1
                # Look at up to 10 lines before the def for decorators
                start = max(0, match.start() - 500)
                context = source[start : match.start() + len(match.group())]
                if require_pattern.search(context):
                    covered += 1

    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.debug("Endpoint coverage scan failed: %s", exc)
        return {"covered_endpoints": 0, "total_endpoints": 0, "coverage_pct": 0.0}

    if total == 0:
        return {"covered_endpoints": 0, "total_endpoints": 0, "coverage_pct": 0.0}

    coverage_pct = round(covered / total * 100, 1)
    return {
        "covered_endpoints": covered,
        "total_endpoints": total,
        "coverage_pct": coverage_pct,
    }
