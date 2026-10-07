"""Notification priority and event-type enums shared by events and the control plane.

The control plane's channel router (:mod:`aragora.control_plane.channels`)
re-exports both names, so lower layers can use them without importing the
control plane.
"""

from __future__ import annotations

from enum import Enum


class NotificationPriority(Enum):
    """Notification priority levels."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"


class NotificationEventType(Enum):
    """Types of events that trigger notifications."""

    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_SUBMITTED = "task_submitted"
    TASK_CLAIMED = "task_claimed"
    TASK_TIMEOUT = "task_timeout"
    TASK_RETRIED = "task_retried"
    TASK_CANCELLED = "task_cancelled"
    DELIBERATION_STARTED = "deliberation_started"
    DELIBERATION_CONSENSUS = "deliberation_consensus"
    DELIBERATION_FAILED = "deliberation_failed"
    AGENT_REGISTERED = "agent_registered"
    AGENT_OFFLINE = "agent_offline"
    AGENT_ERROR = "agent_error"
    SLA_WARNING = "sla_warning"
    SLA_VIOLATION = "sla_violation"
    POLICY_VIOLATION = "policy_violation"
    SYSTEM_ALERT = "system_alert"
    CONNECTOR_SYNC_COMPLETE = "connector_sync_complete"
    CONNECTOR_SYNC_FAILED = "connector_sync_failed"


__all__ = ["NotificationEventType", "NotificationPriority"]
