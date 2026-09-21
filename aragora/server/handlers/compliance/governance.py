"""
Consolidated Governance Handlers for Aragora Compliance Domain.

This module re-exports governance-related handlers from their original locations:
- policy.py - Policy and compliance CRUD operations, violation tracking
- compliance_handler.py - Enterprise compliance (SOC 2, GDPR, legal holds)

This consolidation provides a single entry point for all governance functionality
while maintaining backward compatibility with existing imports.

Endpoints consolidated:
    # From policy.py
    GET  /api/v1/policies                    - List policies
    GET  /api/v1/policies/:id                - Get policy details
    POST /api/v1/policies                    - Create policy
    PATCH /api/v1/policies/:id               - Update policy
    DELETE /api/v1/policies/:id              - Delete policy
    POST /api/v1/policies/:id/toggle         - Toggle policy enabled status
    GET  /api/v1/policies/:id/violations     - Get violations for a policy
    GET  /api/v1/compliance/violations       - List all violations
    GET  /api/v1/compliance/violations/:id   - Get violation details
    PATCH /api/v1/compliance/violations/:id  - Update violation status
    POST /api/v1/compliance/check            - Run compliance check on content
    GET  /api/v1/compliance/stats            - Get compliance statistics

    # From compliance_handler.py
    GET  /api/v2/compliance/status               - Overall compliance status
    GET  /api/v2/compliance/soc2-report          - Generate SOC 2 compliance summary
    GET  /api/v2/compliance/gdpr-export          - Export user data for GDPR
    POST /api/v2/compliance/gdpr/right-to-be-forgotten - Execute GDPR right to erasure
    POST /api/v2/compliance/audit-verify         - Verify audit trail integrity
    GET  /api/v2/compliance/audit-events         - Export audit events (SIEM)
    GET  /api/v2/compliance/gdpr/deletions       - List scheduled deletions
    GET  /api/v2/compliance/gdpr/deletions/:id   - Get deletion request
    POST /api/v2/compliance/gdpr/deletions/:id/cancel - Cancel deletion
    GET  /api/v2/compliance/gdpr/legal-holds     - List legal holds
    POST /api/v2/compliance/gdpr/legal-holds     - Create legal hold
    DELETE /api/v2/compliance/gdpr/legal-holds/:id - Release legal hold
    POST /api/v2/compliance/gdpr/coordinated-deletion - Backup-aware deletion
    POST /api/v2/compliance/gdpr/execute-pending - Execute pending deletions
    GET  /api/v2/compliance/gdpr/backup-exclusions - List backup exclusions
    POST /api/v2/compliance/gdpr/backup-exclusions - Add backup exclusion
"""

from __future__ import annotations

from aragora.rbac.decorators import require_permission

# RBAC permissions for governance endpoints
GOVERNANCE_READ_PERMISSION = "governance:read"
GOVERNANCE_WRITE_PERMISSION = "governance:write"

# Re-export from policy.py
from aragora.server.handlers.governance.policy import (
    PolicyHandler,
)

# Re-export from compliance/handler.py
from aragora.server.handlers.compliance.handler import (
    ComplianceHandler,
    create_compliance_handler,
)

__all__ = [
    # RBAC
    "require_permission",
    "GOVERNANCE_READ_PERMISSION",
    "GOVERNANCE_WRITE_PERMISSION",
    # policy.py exports
    "PolicyHandler",
    # compliance_handler.py exports
    "ComplianceHandler",
    "create_compliance_handler",
]
