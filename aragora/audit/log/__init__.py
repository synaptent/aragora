"""Compatibility re-export of :mod:`aragora.observability.audit_log`.

The compliance audit log moved to the observability layer so that storage, debate,
RLM, RBAC and compliance code can record audit events without importing
``aragora.audit``. Every name below is the identical object, so the audit log
singleton is shared with the new path. Module-level state
(``_audit_log_instance``, ``require_distributed_store``) lives only in the new
module; patch or reset it there.
"""

from __future__ import annotations

from aragora.observability.audit_log import (
    AuditCategory,
    AuditEvent,
    AuditLog,
    AuditOutcome,
    AuditQuery,
    audit_admin_action,
    audit_auth_login,
    audit_data_access,
    get_audit_log,
    reset_audit_log,
)

__all__ = [
    "AuditCategory",
    "AuditEvent",
    "AuditLog",
    "AuditOutcome",
    "AuditQuery",
    "audit_admin_action",
    "audit_auth_login",
    "audit_data_access",
    "get_audit_log",
    "reset_audit_log",
]
