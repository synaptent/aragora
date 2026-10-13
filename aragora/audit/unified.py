"""Compatibility re-export of :mod:`aragora.observability.unified_audit`.

The unified audit facade moved to the observability layer together with the
compliance audit log. Every name below is the identical object, so the unified
logger singleton is shared with the new path. Module-level state
(``_unified_logger``) lives only in the new module; patch or reset it there.
"""

from __future__ import annotations

from aragora.observability.unified_audit import (
    AuditOutcome,
    AuditSeverity,
    UnifiedAuditCategory,
    UnifiedAuditEvent,
    UnifiedAuditLogger,
    audit_access,
    audit_action,
    audit_admin,
    audit_data,
    audit_debate,
    audit_log,
    audit_login,
    audit_logout,
    audit_security,
    configure_unified_audit_logger,
    get_unified_audit_logger,
)

__all__ = [
    "UnifiedAuditCategory",
    "AuditOutcome",
    "AuditSeverity",
    "UnifiedAuditEvent",
    "UnifiedAuditLogger",
    "get_unified_audit_logger",
    "configure_unified_audit_logger",
    "audit_log",
    "audit_login",
    "audit_logout",
    "audit_access",
    "audit_data",
    "audit_admin",
    "audit_security",
    "audit_debate",
    "audit_action",
]
