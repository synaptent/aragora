"""
Audit Bridge - Comprehensive audit logging for external agent actions.

Provides full audit trail for compliance:
- Execution start/complete events
- Credential access logging
- Policy decision logging
- Capability usage tracking
- Integration with existing aragora audit infrastructure

Security Model:
1. Every external agent action is logged
2. Audit events include full context (tenant, user, agent, task)
3. HMAC signing for tamper detection
4. Structured format for SIEM integration
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from aragora.gateway.external_agents.base import (
        ExternalAgentResult,
        ExternalAgentTask,
    )
    from aragora.gateway.external_agents.policy import PolicyDecision

logger = logging.getLogger(__name__)


class AuditEventType(str, Enum):
    """Types of audit events for external agent gateway."""

    # Execution lifecycle
    EXECUTION_START = "external_agent.execution.start"
    EXECUTION_COMPLETE = "external_agent.execution.complete"
    EXECUTION_FAILED = "external_agent.execution.failed"
    EXECUTION_TIMEOUT = "external_agent.execution.timeout"

    # Policy
    POLICY_DECISION = "external_agent.policy.decision"
    POLICY_VIOLATION = "external_agent.policy.violation"

    # Credentials
    CREDENTIAL_ACCESS = "external_agent.credential.access"
    CREDENTIAL_DENIED = "external_agent.credential.denied"

    # Capabilities
    CAPABILITY_USED = "external_agent.capability.used"
    CAPABILITY_BLOCKED = "external_agent.capability.blocked"

    # Security
    OUTPUT_REDACTED = "external_agent.output.redacted"
    SANDBOX_ESCAPE_ATTEMPT = "external_agent.sandbox.escape_attempt"


@dataclass
class AuditEvent:
    """An audit event for external agent gateway."""

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: AuditEventType = AuditEventType.EXECUTION_START
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Context
    tenant_id: str | None = None
    user_id: str | None = None
    workspace_id: str | None = None

    # Agent context
    agent_name: str | None = None
    agent_version: str | None = None
    task_id: str | None = None

    # Event details
    details: dict[str, Any] = field(default_factory=dict)
    severity: str = "info"  # "debug", "info", "warning", "error", "critical"

    # Security
    signature: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "workspace_id": self.workspace_id,
            "agent_name": self.agent_name,
            "agent_version": self.agent_version,
            "task_id": self.task_id,
            "details": self.details,
            "severity": self.severity,
            "signature": self.signature,
        }


class AuditBridge:
    """
    Bridge for audit logging of external agent operations.

    Provides comprehensive audit trail with:
    - HMAC signing for tamper detection
    - Structured events for SIEM integration
    - Integration with existing aragora audit infrastructure
    - Async logging for performance

    Usage:
        bridge = AuditBridge()

        await bridge.log_execution_start(
            adapter_name="openclaw",
            task=task,
            tenant_id="acme-corp",
        )
    """

    def __init__(
        self,
        signing_key: bytes | None = None,
        storage_backend: Any | None = None,
        enable_signing: bool = True,
    ):
        self._signing_key = signing_key or self._get_signing_key()
        self._storage = storage_backend
        self._enable_signing = enable_signing
        self._event_buffer: list[AuditEvent] = []
        self._buffer_size = 100

    def _get_signing_key(self) -> bytes:
        """Get HMAC signing key from environment."""
        env_key = os.environ.get("ARAGORA_AUDIT_SIGNING_KEY")
        if env_key:
            return hashlib.sha256(env_key.encode()).digest()
        logger.warning(
            "Using default audit signing key - configure ARAGORA_AUDIT_SIGNING_KEY for production"
        )
        return hashlib.sha256(b"aragora-audit-default-key").digest()

    def _sign_event(self, event: AuditEvent) -> str:
        """Create HMAC signature for event."""
        content = json.dumps(
            {
                "event_id": event.event_id,
                "event_type": event.event_type.value,
                "timestamp": event.timestamp.isoformat(),
                "tenant_id": event.tenant_id,
                "task_id": event.task_id,
                "details": event.details,
            },
            sort_keys=True,
        )
        return hmac.new(
            self._signing_key,
            content.encode(),
            hashlib.sha256,
        ).hexdigest()

    async def _emit(self, event: AuditEvent) -> None:
        """Emit an audit event."""
        if self._enable_signing:
            event.signature = self._sign_event(event)

        # Log to standard logger
        log_level = {
            "debug": logging.DEBUG,
            "info": logging.INFO,
            "warning": logging.WARNING,
            "error": logging.ERROR,
            "critical": logging.CRITICAL,
        }.get(event.severity, logging.INFO)

        logger.log(
            log_level,
            "[AUDIT] %s: agent=%s task=%s tenant=%s",
            event.event_type.value,
            event.agent_name,
            event.task_id,
            event.tenant_id,
            extra={"audit_event": event.to_dict()},
        )

        # Buffer for batch persistence
        self._event_buffer.append(event)

        # Flush if buffer full
        if len(self._event_buffer) >= self._buffer_size:
            await self._flush_buffer()

        # Send to storage backend if configured
        if self._storage:
            try:
                await self._storage.store_event(event.to_dict())
            except (OSError, ConnectionError, RuntimeError) as e:
                logger.error("Failed to store audit event: %s", e)

    async def _flush_buffer(self) -> None:
        """Flush buffered events to storage."""
        if not self._event_buffer:
            return

        if self._storage:
            try:
                events = [e.to_dict() for e in self._event_buffer]
                await self._storage.store_events_batch(events)
            except (OSError, ConnectionError, RuntimeError) as e:
                logger.error("Failed to flush audit buffer: %s", e)

        self._event_buffer.clear()

    async def log_execution_start(
        self,
        adapter_name: str,
        task: ExternalAgentTask,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> str:
        """Log the start of an external agent execution."""
        event = AuditEvent(
            event_type=AuditEventType.EXECUTION_START,
            tenant_id=tenant_id or task.tenant_id,
            user_id=user_id or task.user_id,
            workspace_id=task.workspace_id,
            agent_name=adapter_name,
            task_id=task.task_id,
            details={
                "task_type": task.task_type,
                "required_capabilities": [c.value for c in task.required_capabilities],
                "timeout_seconds": task.timeout_seconds,
                "prompt_length": len(task.prompt),
            },
        )
        await self._emit(event)
        return event.event_id

    async def log_execution_complete(
        self,
        result: ExternalAgentResult,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> str:
        """Log the completion of an external agent execution."""
        event_type = (
            AuditEventType.EXECUTION_COMPLETE if result.success else AuditEventType.EXECUTION_FAILED
        )
        severity = "info" if result.success else "warning"

        event = AuditEvent(
            event_type=event_type,
            tenant_id=tenant_id,
            user_id=user_id,
            agent_name=result.agent_name,
            agent_version=result.agent_version,
            task_id=result.task_id,
            severity=severity,
            details={
                "success": result.success,
                "error": result.error,
                "execution_time_ms": result.execution_time_ms,
                "tokens_used": result.tokens_used,
                "capabilities_used": [c.value for c in result.capabilities_used],
                "was_sandboxed": result.was_sandboxed,
                "isolation_level": result.isolation_level.value,
                "output_redacted": result.output_redacted,
                "redaction_count": result.redaction_count,
                "output_length": len(result.output),
            },
        )
        await self._emit(event)
        return event.event_id

    async def log_policy_decision(
        self,
        policy_id: str,
        adapter_name: str,
        task_id: str,
        tenant_id: str | None,
        user_id: str | None,
        decision: PolicyDecision,
    ) -> str:
        """Log a policy decision."""
        event_type = (
            AuditEventType.POLICY_DECISION if decision.allowed else AuditEventType.POLICY_VIOLATION
        )
        severity = "info" if decision.allowed else "warning"

        event = AuditEvent(
            event_type=event_type,
            tenant_id=tenant_id,
            user_id=user_id,
            agent_name=adapter_name,
            task_id=task_id,
            severity=severity,
            details={
                "policy_id": policy_id,
                "allowed": decision.allowed,
                "action": decision.action.value,
                "reason": decision.reason,
                "requires_approval": decision.requires_approval,
                "warnings": decision.warnings,
            },
        )
        await self._emit(event)
        return event.event_id

    async def log_credential_access(
        self,
        agent_name: str,
        tenant_id: str | None,
        credentials_accessed: list[str],
    ) -> str:
        """Log credential access by an external agent."""
        event = AuditEvent(
            event_type=AuditEventType.CREDENTIAL_ACCESS,
            tenant_id=tenant_id,
            agent_name=agent_name,
            details={
                "credentials_accessed": credentials_accessed,
                "credential_count": len(credentials_accessed),
            },
        )
        await self._emit(event)
        return event.event_id

    async def log_output_redaction(
        self,
        agent_name: str,
        task_id: str,
        tenant_id: str | None,
        redaction_count: int,
        redacted_types: dict[str, int],
    ) -> str:
        """Log output redaction event."""
        event = AuditEvent(
            event_type=AuditEventType.OUTPUT_REDACTED,
            tenant_id=tenant_id,
            agent_name=agent_name,
            task_id=task_id,
            details={
                "redaction_count": redaction_count,
                "redacted_types": redacted_types,
            },
        )
        await self._emit(event)
        return event.event_id

    async def log_capability_usage(
        self,
        agent_name: str,
        task_id: str,
        tenant_id: str | None,
        capability: str,
        allowed: bool,
    ) -> str:
        """Log capability usage or block."""
        event_type = (
            AuditEventType.CAPABILITY_USED if allowed else AuditEventType.CAPABILITY_BLOCKED
        )
        severity = "info" if allowed else "warning"

        event = AuditEvent(
            event_type=event_type,
            tenant_id=tenant_id,
            agent_name=agent_name,
            task_id=task_id,
            severity=severity,
            details={
                "capability": capability,
                "allowed": allowed,
            },
        )
        await self._emit(event)
        return event.event_id

    async def close(self) -> None:
        """Flush any remaining events and close."""
        await self._flush_buffer()
