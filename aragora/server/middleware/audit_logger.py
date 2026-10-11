"""
Audit Logging Middleware.

DEPRECATION NOTICE:
    This module provides HTTP middleware-specific audit logging. For new code,
    use the unified audit system in aragora.audit instead:

        from aragora.audit import AuditLog, AuditEvent, AuditCategory

    The unified system supports all audit categories including AUTH, ACCESS,
    API, and SECURITY events with compliance export (SOC 2, GDPR, HIPAA).

    This module is maintained for backward compatibility with existing
    middleware code that depends on AuditSeverity and audit_event().

Provides security-focused audit logging for sensitive operations:
- Authentication events (login, logout, token refresh, revocation)
- Authorization events (permission checks, access denied)
- Data modification events (create, update, delete)
- Administrative actions (config changes, user management)

Features:
- Structured audit entries with unique IDs
- Tamper-evident logging with hash chains
- Multiple backends (file, database, remote)
- Async-safe with context propagation
- Configurable retention and severity levels

Usage:
    from aragora.server.middleware.audit_logger import (
        audit_event,
        AuditEvent,
        AuditSeverity,
        get_audit_logger,
    )

    # Log an authentication event
    audit_event(
        action="user.login",
        actor="user@example.com",
        resource="auth/session",
        outcome="success",
        severity=AuditSeverity.INFO,
        details={"method": "password", "mfa": True},
    )

    # Use as decorator for automatic auditing
    @audit_action("debate.create", resource_from="debate_id")
    async def create_debate(self, handler, debate_id: str):
        ...
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Any, Protocol
from collections.abc import Callable

logger = logging.getLogger(__name__)


class AuditSeverity(Enum):
    """Severity levels for audit events."""

    DEBUG = "debug"  # Detailed diagnostic events
    INFO = "info"  # Normal operations (successful auth, data access)
    WARNING = "warning"  # Anomalous but not critical (failed auth attempts)
    ERROR = "error"  # Failures that need attention
    CRITICAL = "critical"  # Security incidents requiring immediate action


class AuditCategory(Enum):
    """Categories for audit events."""

    AUTHENTICATION = "authentication"  # Login, logout, token operations
    AUTHORIZATION = "authorization"  # Permission checks, access control
    DATA_ACCESS = "data_access"  # Read operations on sensitive data
    DATA_MODIFICATION = "data_modification"  # Create, update, delete
    CONFIGURATION = "configuration"  # System config changes
    ADMINISTRATIVE = "administrative"  # User management, role changes
    SECURITY = "security"  # Security-related events (rate limits, blocks)
    SYSTEM = "system"  # System events (startup, shutdown)


@dataclass
class AuditEvent:
    """
    A single audit log entry.

    Follows the "who, what, when, where, why, how" audit model.
    """

    # Event identification (required)
    event_id: str  # Unique event ID
    timestamp: datetime  # When the event occurred
    actor: str  # User ID, service name, or "system"
    action: str  # Action name (e.g., "user.login", "debate.create")

    # Who (actor) - optional details
    actor_ip: str | None = None  # Client IP address
    actor_type: str = "user"  # "user", "service", "system", "anonymous"

    # What (action) - optional details
    category: AuditCategory = AuditCategory.SYSTEM
    severity: AuditSeverity = AuditSeverity.INFO

    # Where (resource)
    resource: str = ""  # Resource being acted upon
    resource_id: str | None = None  # Specific resource ID
    resource_type: str | None = None  # Type of resource

    # Result
    outcome: str = "success"  # "success", "failure", "denied", "error"
    outcome_reason: str | None = None  # Reason for outcome

    # Context
    request_id: str | None = None  # Correlation ID
    session_id: str | None = None  # Session ID if applicable
    details: dict[str, Any] = field(default_factory=dict)  # Additional context

    # Integrity
    previous_hash: str | None = None  # Hash of previous event (chain)
    event_hash: str | None = None  # Hash of this event

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "actor": self.actor,
            "actor_ip": self.actor_ip,
            "actor_type": self.actor_type,
            "action": self.action,
            "category": self.category.value,
            "severity": self.severity.value,
            "resource": self.resource,
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "outcome": self.outcome,
            "outcome_reason": self.outcome_reason,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "details": self.details,
            "previous_hash": self.previous_hash,
            "event_hash": self.event_hash,
        }

    def compute_hash(self) -> str:
        """Compute hash of event for integrity verification."""
        # Create deterministic JSON representation
        data = {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "actor": self.actor,
            "action": self.action,
            "resource": self.resource,
            "outcome": self.outcome,
            "previous_hash": self.previous_hash,
        }
        serialized = json.dumps(data, sort_keys=True)
        return hashlib.sha256(serialized.encode()).hexdigest()


class AuditBackend(Protocol):
    """Protocol for audit log backends."""

    def write(self, event: AuditEvent) -> None:
        """Write an audit event."""
        ...

    def query(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        actor: str | None = None,
        action: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """Query audit events."""
        ...

    def get_last_hash(self) -> str | None:
        """Get hash of the last event for chain integrity."""
        ...


class FileAuditBackend:
    """
    File-based audit backend.

    Writes audit events to a JSON Lines file with rotation support.
    """

    def __init__(
        self,
        log_dir: str | None = None,
        file_prefix: str = "audit",
        max_file_size_mb: int = 100,
        retention_days: int = 90,
    ):
        """
        Initialize the file backend.

        Args:
            log_dir: Directory for audit logs (defaults to AUDIT_LOG_DIR env var)
            file_prefix: Prefix for log file names
            max_file_size_mb: Max size before rotation
            retention_days: Days to retain old logs
        """
        self._log_dir = Path(log_dir or os.environ.get("AUDIT_LOG_DIR", "logs/audit"))
        self._log_dir.mkdir(parents=True, exist_ok=True)

        self._file_prefix = file_prefix
        self._max_size = max_file_size_mb * 1024 * 1024
        self._retention_days = retention_days

        self._lock = threading.Lock()
        self._last_hash: str | None = None

        # Load last hash from existing log
        self._load_last_hash()

    def _get_current_file(self) -> Path:
        """Get the current log file path."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._log_dir / f"{self._file_prefix}-{date_str}.jsonl"

    def _load_last_hash(self) -> None:
        """Load the hash of the last event from existing logs."""
        current_file = self._get_current_file()
        if current_file.exists():
            try:
                with open(current_file) as f:
                    lines = f.readlines()
                    if lines:
                        last_event = json.loads(lines[-1])
                        self._last_hash = last_event.get("event_hash")
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load last audit hash: %s", e)

    def write(self, event: AuditEvent) -> None:
        """Write an audit event to file."""
        with self._lock:
            # Set previous hash and compute new hash
            event.previous_hash = self._last_hash
            event.event_hash = event.compute_hash()

            current_file = self._get_current_file()

            # Check for rotation
            if current_file.exists() and current_file.stat().st_size > self._max_size:
                self._rotate_file(current_file)

            # Write event
            try:
                with open(current_file, "a") as f:
                    f.write(json.dumps(event.to_dict()) + "\n")
                self._last_hash = event.event_hash
            except OSError as e:
                logger.error("Failed to write audit event: %s", e)

    def _rotate_file(self, file_path: Path) -> None:
        """Rotate a log file that has exceeded max size."""
        timestamp = datetime.now(timezone.utc).strftime("%H%M%S")
        rotated = file_path.with_suffix(f".{timestamp}.jsonl")
        try:
            file_path.rename(rotated)
            logger.info("Rotated audit log to %s", rotated)
        except OSError as e:
            logger.error("Failed to rotate audit log: %s", e)

    def query(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        actor: str | None = None,
        action: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """Query audit events from files."""
        results: list[AuditEvent] = []

        # Get all log files in date range
        log_files = sorted(self._log_dir.glob(f"{self._file_prefix}-*.jsonl"))

        for log_file in log_files:
            if len(results) >= limit:
                break

            try:
                with open(log_file) as f:
                    for line in f:
                        if len(results) >= limit:
                            break

                        try:
                            data = json.loads(line)
                            event_time = datetime.fromisoformat(data["timestamp"])

                            # Apply filters
                            if start_time and event_time < start_time:
                                continue
                            if end_time and event_time > end_time:
                                continue
                            if actor and data.get("actor") != actor:
                                continue
                            if action and data.get("action") != action:
                                continue

                            # Reconstruct event
                            event = AuditEvent(
                                event_id=data["event_id"],
                                timestamp=event_time,
                                actor=data["actor"],
                                actor_ip=data.get("actor_ip"),
                                actor_type=data.get("actor_type", "user"),
                                action=data["action"],
                                category=AuditCategory(data.get("category", "system")),
                                severity=AuditSeverity(data.get("severity", "info")),
                                resource=data.get("resource", ""),
                                resource_id=data.get("resource_id"),
                                resource_type=data.get("resource_type"),
                                outcome=data.get("outcome", "success"),
                                outcome_reason=data.get("outcome_reason"),
                                request_id=data.get("request_id"),
                                session_id=data.get("session_id"),
                                details=data.get("details", {}),
                                previous_hash=data.get("previous_hash"),
                                event_hash=data.get("event_hash"),
                            )
                            results.append(event)

                        except (json.JSONDecodeError, KeyError, ValueError) as e:
                            logger.warning("Failed to parse audit event: %s", e)

            except OSError as e:
                logger.warning("Failed to read audit file %s: %s", log_file, e)

        return results

    def get_last_hash(self) -> str | None:
        """Get hash of the last event."""
        return self._last_hash


class MemoryAuditBackend:
    """
    In-memory audit backend for testing and development.

    Limited to a configurable number of events.
    """

    def __init__(self, max_events: int = 10000):
        """
        Initialize the memory backend.

        Args:
            max_events: Maximum events to retain
        """
        self._events: list[AuditEvent] = []
        self._max_events = max_events
        self._lock = threading.Lock()
        self._last_hash: str | None = None

    def write(self, event: AuditEvent) -> None:
        """Write an audit event to memory."""
        with self._lock:
            event.previous_hash = self._last_hash
            event.event_hash = event.compute_hash()

            self._events.append(event)
            self._last_hash = event.event_hash

            # Trim if over capacity
            if len(self._events) > self._max_events:
                self._events = self._events[-self._max_events :]

    def query(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        actor: str | None = None,
        action: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """Query audit events from memory."""
        with self._lock:
            results: list[AuditEvent] = []
            for event in self._events:
                if len(results) >= limit:
                    break

                if start_time and event.timestamp < start_time:
                    continue
                if end_time and event.timestamp > end_time:
                    continue
                if actor and event.actor != actor:
                    continue
                if action and event.action != action:
                    continue

                results.append(event)

            return results

    def get_last_hash(self) -> str | None:
        """Get hash of the last event."""
        return self._last_hash

    def clear(self) -> None:
        """Clear all events (for testing)."""
        with self._lock:
            self._events.clear()
            self._last_hash = None


class AuditLogger:
    """
    Main audit logger with multiple backend support.

    Provides high-level API for logging audit events with
    context propagation and async safety.
    """

    def __init__(
        self,
        backend: AuditBackend | None = None,
        service_name: str = "aragora",
        min_severity: AuditSeverity = AuditSeverity.INFO,
    ):
        """
        Initialize the audit logger.

        Args:
            backend: Audit backend (defaults to file backend)
            service_name: Name of the service for events
            min_severity: Minimum severity to log
        """
        self._backend = backend or self._create_default_backend()
        self._service_name = service_name
        self._min_severity = min_severity

    def _create_default_backend(self) -> AuditBackend:
        """Create the default backend based on environment."""
        # Use memory backend in tests, file backend otherwise
        if os.environ.get("TESTING") == "1":
            return MemoryAuditBackend()
        return FileAuditBackend()

    def log(
        self,
        action: str,
        actor: str = "system",
        actor_ip: str | None = None,
        actor_type: str = "user",
        resource: str = "",
        resource_id: str | None = None,
        resource_type: str | None = None,
        outcome: str = "success",
        outcome_reason: str | None = None,
        category: AuditCategory = AuditCategory.SYSTEM,
        severity: AuditSeverity = AuditSeverity.INFO,
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        """
        Log an audit event.

        Args:
            action: Action being performed
            actor: Who performed the action
            actor_ip: IP address of the actor
            actor_type: Type of actor
            resource: Resource being acted upon
            resource_id: ID of the resource
            resource_type: Type of resource
            outcome: Result of the action
            outcome_reason: Reason for the outcome
            category: Event category
            severity: Event severity
            details: Additional context

        Returns:
            The created audit event
        """
        # Check severity threshold
        severity_order = list(AuditSeverity)
        if severity_order.index(severity) < severity_order.index(self._min_severity):
            # Return dummy event without logging
            return AuditEvent(
                event_id="",
                timestamp=datetime.now(timezone.utc),
                actor=actor,
                action=action,
            )

        # Get context
        request_id = _current_request_id.get()
        session_id = _current_session_id.get()

        event = AuditEvent(
            event_id=f"audit-{uuid.uuid4().hex[:16]}",
            timestamp=datetime.now(timezone.utc),
            actor=actor,
            actor_ip=actor_ip,
            actor_type=actor_type,
            action=action,
            category=category,
            severity=severity,
            resource=resource,
            resource_id=resource_id,
            resource_type=resource_type,
            outcome=outcome,
            outcome_reason=outcome_reason,
            request_id=request_id,
            session_id=session_id,
            details=details or {},
        )

        # Write to backend
        self._backend.write(event)

        # Also log to standard logger for immediate visibility
        log_level = self._severity_to_log_level(severity)
        logger.log(
            log_level,
            "AUDIT: %s by %s on %s -> %s",
            action,
            actor,
            resource or "system",
            outcome,
            extra={"audit_event_id": event.event_id, "audit_action": action},
        )

        return event

    def _severity_to_log_level(self, severity: AuditSeverity) -> int:
        """Map audit severity to logging level."""
        mapping = {
            AuditSeverity.DEBUG: logging.DEBUG,
            AuditSeverity.INFO: logging.INFO,
            AuditSeverity.WARNING: logging.WARNING,
            AuditSeverity.ERROR: logging.ERROR,
            AuditSeverity.CRITICAL: logging.CRITICAL,
        }
        return mapping.get(severity, logging.INFO)

    def query(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        actor: str | None = None,
        action: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """Query audit events."""
        return self._backend.query(
            start_time=start_time,
            end_time=end_time,
            actor=actor,
            action=action,
            limit=limit,
        )

    def verify_chain_integrity(self, events: list[AuditEvent]) -> bool:
        """
        Verify the hash chain integrity of a sequence of events.

        Args:
            events: List of events to verify (must be in order)

        Returns:
            True if chain is valid, False if tampering detected
        """
        if not events:
            return True

        for i, event in enumerate(events):
            # Compute expected hash
            expected_hash = event.compute_hash()
            if event.event_hash != expected_hash:
                logger.error(
                    "Audit chain integrity failure: event %s hash mismatch (expected %s, got %s)",
                    event.event_id,
                    expected_hash,
                    event.event_hash,
                )
                return False

            # Verify chain linkage
            if i > 0:
                if event.previous_hash != events[i - 1].event_hash:
                    logger.error(
                        "Audit chain integrity failure: event %s previous_hash does not match preceding event",
                        event.event_id,
                    )
                    return False

        return True


# Global audit logger instance
_audit_logger: AuditLogger | None = None
_logger_lock = threading.Lock()

# Context variables for request/session tracking
_current_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "audit_request_id", default=None
)
_current_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "audit_session_id", default=None
)
_current_actor: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "audit_actor", default=None
)
_current_actor_ip: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "audit_actor_ip", default=None
)


def get_audit_logger() -> AuditLogger:
    """Get the global audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        with _logger_lock:
            if _audit_logger is None:
                _audit_logger = AuditLogger()
    return _audit_logger


def set_audit_logger(logger: AuditLogger) -> None:
    """Set the global audit logger instance."""
    global _audit_logger
    with _logger_lock:
        _audit_logger = logger


def set_audit_context(
    request_id: str | None = None,
    session_id: str | None = None,
    actor: str | None = None,
    actor_ip: str | None = None,
) -> None:
    """Set audit context for the current execution."""
    if request_id is not None:
        _current_request_id.set(request_id)
    if session_id is not None:
        _current_session_id.set(session_id)
    if actor is not None:
        _current_actor.set(actor)
    if actor_ip is not None:
        _current_actor_ip.set(actor_ip)


def clear_audit_context() -> None:
    """Clear audit context for the current execution."""
    _current_request_id.set(None)
    _current_session_id.set(None)
    _current_actor.set(None)
    _current_actor_ip.set(None)


def audit_event(
    action: str,
    actor: str | None = None,
    resource: str = "",
    resource_id: str | None = None,
    outcome: str = "success",
    severity: AuditSeverity = AuditSeverity.INFO,
    category: AuditCategory = AuditCategory.SYSTEM,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """
    Log an audit event using the global logger.

    Convenience function that uses context variables for actor info.

    Args:
        action: Action being performed
        actor: Actor override (uses context if not provided)
        resource: Resource being acted upon
        resource_id: ID of the resource
        outcome: Result of the action
        severity: Event severity
        category: Event category
        details: Additional context

    Returns:
        The created audit event
    """
    audit_logger = get_audit_logger()

    return audit_logger.log(
        action=action,
        actor=actor or _current_actor.get() or "unknown",
        actor_ip=_current_actor_ip.get(),
        resource=resource,
        resource_id=resource_id,
        outcome=outcome,
        severity=severity,
        category=category,
        details=details,
    )


def audit_action(
    action: str,
    category: AuditCategory = AuditCategory.SYSTEM,
    severity: AuditSeverity = AuditSeverity.INFO,
    resource_from: str | None = None,
    resource_id_from: str | None = None,
) -> Callable:
    """
    Decorator for automatic audit logging of function calls.

    Args:
        action: Action name for audit log
        category: Event category
        severity: Event severity (may be elevated on failure)
        resource_from: Kwarg name to use as resource
        resource_id_from: Kwarg name to use as resource_id

    Returns:
        Decorator function

    Example:
        @audit_action("debate.create", category=AuditCategory.DATA_MODIFICATION)
        async def create_debate(self, handler, debate_id: str):
            ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            resource = ""
            resource_id = None

            if resource_from:
                resource = str(kwargs.get(resource_from, ""))
            if resource_id_from:
                resource_id = kwargs.get(resource_id_from)

            start_time = time.time()
            outcome = "success"
            outcome_reason = None
            event_severity = severity

            try:
                result = await func(*args, **kwargs)
                return result

            except PermissionError as e:
                outcome = "denied"
                outcome_reason = f"Permission denied: {type(e).__name__}"
                event_severity = AuditSeverity.WARNING
                logger.warning("Audit: permission denied in %s: %s", action, e)
                raise

            except (
                Exception  # noqa: BLE001 - audit decorator logs all failures before re-raising
            ) as e:
                outcome = "error"
                outcome_reason = f"Operation failed: {type(e).__name__}"
                event_severity = AuditSeverity.ERROR
                logger.warning("Audit: error in %s: %s", action, e)
                raise

            finally:
                elapsed_ms = (time.time() - start_time) * 1000
                audit_event(
                    action=action,
                    resource=resource,
                    resource_id=resource_id,
                    outcome=outcome,
                    severity=event_severity,
                    category=category,
                    details={
                        "elapsed_ms": round(elapsed_ms, 2),
                        "outcome_reason": outcome_reason,
                    },
                )

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            resource = ""
            resource_id = None

            if resource_from:
                resource = str(kwargs.get(resource_from, ""))
            if resource_id_from:
                resource_id = kwargs.get(resource_id_from)

            start_time = time.time()
            outcome = "success"
            outcome_reason = None
            event_severity = severity

            try:
                result = func(*args, **kwargs)
                return result

            except PermissionError as e:
                outcome = "denied"
                outcome_reason = f"Permission denied: {type(e).__name__}"
                event_severity = AuditSeverity.WARNING
                logger.warning("Audit: permission denied in %s: %s", action, e)
                raise

            except (
                Exception  # noqa: BLE001 - audit decorator logs all failures before re-raising
            ) as e:
                outcome = "error"
                outcome_reason = f"Operation failed: {type(e).__name__}"
                event_severity = AuditSeverity.ERROR
                logger.warning("Audit: error in %s: %s", action, e)
                raise

            finally:
                elapsed_ms = (time.time() - start_time) * 1000
                audit_event(
                    action=action,
                    resource=resource,
                    resource_id=resource_id,
                    outcome=outcome,
                    severity=event_severity,
                    category=category,
                    details={
                        "elapsed_ms": round(elapsed_ms, 2),
                        "outcome_reason": outcome_reason,
                    },
                )

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# Pre-defined audit event helpers for common operations


def audit_auth_login(
    user_id: str,
    success: bool,
    method: str = "password",
    ip_address: str | None = None,
    reason: str | None = None,
) -> AuditEvent:
    """Log an authentication login attempt."""
    return audit_event(
        action="auth.login",
        actor=user_id,
        resource="auth/session",
        outcome="success" if success else "failure",
        severity=AuditSeverity.INFO if success else AuditSeverity.WARNING,
        category=AuditCategory.AUTHENTICATION,
        details={
            "method": method,
            "ip_address": ip_address,
            "failure_reason": reason if not success else None,
        },
    )


def audit_auth_logout(user_id: str, ip_address: str | None = None) -> AuditEvent:
    """Log an authentication logout."""
    return audit_event(
        action="auth.logout",
        actor=user_id,
        resource="auth/session",
        outcome="success",
        severity=AuditSeverity.INFO,
        category=AuditCategory.AUTHENTICATION,
        details={"ip_address": ip_address},
    )


def audit_token_revoked(
    token_hash: str,
    revoked_by: str,
    reason: str,
) -> AuditEvent:
    """Log a token revocation."""
    return audit_event(
        action="auth.token_revoked",
        actor=revoked_by,
        resource="auth/token",
        resource_id=token_hash[:8],  # Truncated for privacy
        outcome="success",
        severity=AuditSeverity.INFO,
        category=AuditCategory.AUTHENTICATION,
        details={"reason": reason},
    )


def audit_access_denied(
    user_id: str,
    resource: str,
    required_permission: str,
    ip_address: str | None = None,
) -> AuditEvent:
    """Log an access denied event."""
    return audit_event(
        action="authz.access_denied",
        actor=user_id,
        resource=resource,
        outcome="denied",
        severity=AuditSeverity.WARNING,
        category=AuditCategory.AUTHORIZATION,
        details={
            "required_permission": required_permission,
            "ip_address": ip_address,
        },
    )


def audit_data_modified(
    user_id: str,
    resource_type: str,
    resource_id: str,
    operation: str,  # "create", "update", "delete"
    changes: dict[str, Any] | None = None,
) -> AuditEvent:
    """Log a data modification event."""
    return audit_event(
        action=f"data.{operation}",
        actor=user_id,
        resource=resource_type,
        resource_id=resource_id,
        outcome="success",
        severity=AuditSeverity.INFO,
        category=AuditCategory.DATA_MODIFICATION,
        details={"changes": changes or {}},
    )


def audit_config_changed(
    user_id: str,
    config_key: str,
    old_value: str | None = None,
    new_value: str | None = None,
) -> AuditEvent:
    """Log a configuration change."""
    return audit_event(
        action="config.changed",
        actor=user_id,
        resource="configuration",
        resource_id=config_key,
        outcome="success",
        severity=AuditSeverity.WARNING,  # Config changes are notable
        category=AuditCategory.CONFIGURATION,
        details={
            "old_value": old_value,
            "new_value": new_value,
        },
    )


def audit_security_event(
    event_type: str,  # "rate_limit", "blocked_ip", "suspicious_activity"
    actor: str,
    details: dict[str, Any],
    severity: AuditSeverity = AuditSeverity.WARNING,
) -> AuditEvent:
    """Log a security-related event."""
    return audit_event(
        action=f"security.{event_type}",
        actor=actor,
        resource="security",
        outcome="detected",
        severity=severity,
        category=AuditCategory.SECURITY,
        details=details,
    )


__all__ = [
    # Core classes
    "AuditEvent",
    "AuditLogger",
    "AuditSeverity",
    "AuditCategory",
    # Backends
    "AuditBackend",
    "FileAuditBackend",
    "MemoryAuditBackend",
    # Global logger
    "get_audit_logger",
    "set_audit_logger",
    # Context management
    "set_audit_context",
    "clear_audit_context",
    # Event logging
    "audit_event",
    "audit_action",
    # Pre-defined events
    "audit_auth_login",
    "audit_auth_logout",
    "audit_token_revoked",
    "audit_access_denied",
    "audit_data_modified",
    "audit_config_changed",
    "audit_security_event",
]
