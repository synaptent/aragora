"""
Consolidated Audit Handlers for Aragora Compliance Domain.

This module re-exports audit-related handlers from their original locations:
- audit_export.py - Audit log query and compliance exports
- audit_trail.py - Audit trail access and verification
- auditing.py - Security auditing and capability probing

This consolidation provides a single entry point for all audit functionality
while maintaining backward compatibility with existing imports.

Endpoints consolidated:
    # From audit_export.py
    GET  /api/v1/audit/events      - Query audit events
    GET  /api/v1/audit/stats       - Audit log statistics
    POST /api/v1/audit/export      - Export audit log (JSON, CSV, SOC2)
    POST /api/v1/audit/verify      - Verify audit log integrity

    # From audit_trail.py
    GET  /api/v1/audit-trails                    - List recent audit trails
    GET  /api/v1/audit-trails/:trail_id          - Get specific audit trail
    GET  /api/v1/audit-trails/:trail_id/export   - Export (format=json|csv|md)
    POST /api/v1/audit-trails/:trail_id/verify   - Verify integrity checksum
    GET  /api/v1/receipts                        - List recent decision receipts
    GET  /api/v1/receipts/:receipt_id            - Get specific receipt
    POST /api/v1/receipts/:receipt_id/verify     - Verify receipt integrity

    # From auditing.py
    POST /api/v1/debates/capability-probe - Run capability probes on an agent
    POST /api/v1/debates/deep-audit       - Run deep audit on a task
    POST /api/v1/debates/:id/red-team     - Run red team analysis on a debate
    GET  /api/v1/redteam/attack-types     - Get available attack types
"""

from __future__ import annotations

from aragora.rbac.decorators import require_permission

# RBAC permissions for audit endpoints
AUDIT_READ_PERMISSION = "audit:read"
AUDIT_EXPORT_PERMISSION = "audit:export"

# Re-export from audit_export.py
from aragora.server.handlers.compliance.audit_export import (
    handle_audit_events,
    handle_audit_export,
    handle_audit_stats,
    handle_audit_verify,
    register_handlers,
    get_audit_log,
)

# Re-export from audit_trail.py
from aragora.server.handlers.compliance.audit_trail import (
    AuditTrailHandler,
)

# Re-export from auditing.py
from aragora.server.handlers.auditing import (
    AuditRequestParser,
    AuditAgentFactory,
    AuditResultRecorder,
    AuditingHandler,
)

__all__ = [
    # RBAC
    "require_permission",
    "AUDIT_READ_PERMISSION",
    "AUDIT_EXPORT_PERMISSION",
    # audit_export.py exports
    "handle_audit_events",
    "handle_audit_export",
    "handle_audit_stats",
    "handle_audit_verify",
    "register_handlers",
    "get_audit_log",
    # audit_trail.py exports
    "AuditTrailHandler",
    # auditing.py exports
    "AuditRequestParser",
    "AuditAgentFactory",
    "AuditResultRecorder",
    "AuditingHandler",
]
