"""
Compliance HTTP Handlers for Aragora.

Provides REST API endpoints for compliance and audit operations:
- SOC 2 Type II report generation
- GDPR data export requests and Right-to-be-Forgotten workflow
- CCPA compliance (Right to Know, Delete, Opt-Out, Correct)
- HIPAA compliance (PHI access logging, breach assessment, BAA management)
- Audit trail verification
- SIEM-compatible event export
- Legal hold management

Endpoints:
    # General
    GET  /api/v2/compliance/status               - Overall compliance status
    POST /api/v2/compliance/audit-verify         - Verify audit trail integrity
    GET  /api/v2/compliance/audit-events         - Export audit events (SIEM)

    # SOC 2
    GET  /api/v2/compliance/soc2-report          - Generate SOC 2 compliance summary

    # GDPR
    GET  /api/v2/compliance/gdpr-export          - Export user data for GDPR
    POST /api/v2/compliance/gdpr/right-to-be-forgotten - Execute GDPR right to erasure
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

    # CCPA
    GET  /api/v2/compliance/ccpa/disclosure      - Right to Know disclosure
    POST /api/v2/compliance/ccpa/delete          - Right to Delete
    POST /api/v2/compliance/ccpa/opt-out         - Right to Opt-Out
    POST /api/v2/compliance/ccpa/correct         - Right to Correct
    GET  /api/v2/compliance/ccpa/status          - CCPA request status

    # HIPAA
    GET  /api/v2/compliance/hipaa/status         - HIPAA compliance status
    GET  /api/v2/compliance/hipaa/phi-access     - PHI access audit log
    POST /api/v2/compliance/hipaa/breach-assessment - Breach risk assessment
    GET  /api/v2/compliance/hipaa/baa            - List Business Associate Agreements
    POST /api/v2/compliance/hipaa/baa            - Register new BAA
    GET  /api/v2/compliance/hipaa/security-report - Security Rule compliance report

    # EU AI Act
    POST /api/v2/compliance/eu-ai-act/classify         - Classify AI use case risk level
    POST /api/v2/compliance/eu-ai-act/audit            - Generate conformity report
    POST /api/v2/compliance/eu-ai-act/generate-bundle  - Generate full artifact bundle

These endpoints support enterprise compliance requirements.
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.events.handler_events import emit_handler_event, QUERIED
from aragora.server.handlers.base import BaseHandler, HandlerResult, error_response
from aragora.server.handlers.utils.rate_limit import rate_limit
from aragora.rbac.decorators import PermissionDeniedError, require_permission
from aragora.observability.metrics import track_handler

from .soc2 import SOC2Mixin
from .gdpr import GDPRMixin
from .ccpa import CCPAMixin
from .hipaa import HIPAAMixin
from .legal_hold import LegalHoldMixin
from .audit_verify import AuditVerifyMixin, parse_timestamp
from .eu_ai_act import EUAIActMixin

logger = logging.getLogger(__name__)


class ComplianceHandler(
    BaseHandler,
    SOC2Mixin,
    GDPRMixin,
    CCPAMixin,
    HIPAAMixin,
    LegalHoldMixin,
    AuditVerifyMixin,
    EUAIActMixin,
):
    """
    HTTP handler for compliance and audit operations.

    Provides REST API access to compliance reports, GDPR exports,
    CCPA compliance, HIPAA compliance, and audit verification.

    Uses mixins to organize functionality:
    - SOC2Mixin: SOC 2 Type II report generation and control evaluation
    - GDPRMixin: GDPR data export, right-to-be-forgotten, deletion management
    - CCPAMixin: CCPA Right to Know, Delete, Opt-Out, Correct
    - HIPAAMixin: HIPAA PHI access logging, breach assessment, BAA management
    - LegalHoldMixin: Legal hold creation, listing, and release
    - AuditVerifyMixin: Audit trail verification and SIEM event export
    - EUAIActMixin: EU AI Act risk classification, conformity reports, artifact bundles
    """

    ROUTES = [
        "/api/v1/compliance/rbac-coverage",
        "/api/v2/compliance",
        "/api/v2/compliance/*",
    ]

    def __init__(self, server_context: dict[str, Any]):
        """Initialize with server context."""
        super().__init__(server_context)

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the request."""
        if path == "/api/v1/compliance/rbac-coverage":
            return method == "GET"
        if path.startswith("/api/v2/compliance"):
            return method in ("GET", "POST", "DELETE")
        return False

    @require_permission("compliance:read")
    @track_handler("compliance/main", method="GET")
    @rate_limit(requests_per_minute=20)
    async def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Route request to appropriate handler method."""
        method: str = getattr(handler, "command", "GET") if handler else "GET"
        body: dict[str, Any] = (self.read_json_body(handler) or {}) if handler else {}
        headers: dict[str, str] | None = (
            dict(handler.headers) if handler and hasattr(handler, "headers") else None
        )
        query_params = query_params or {}

        try:
            # RBAC coverage endpoint (v1)
            if path == "/api/v1/compliance/rbac-coverage" and method == "GET":
                return await self._get_rbac_coverage()

            # Status endpoint
            if path == "/api/v2/compliance/status" and method == "GET":
                emit_handler_event("compliance", QUERIED, {"endpoint": "status"})
                return await self._get_status()

            # SOC 2 report endpoint
            if path == "/api/v2/compliance/soc2-report" and method == "GET":
                return await self._get_soc2_report(query_params)

            # GDPR export endpoint
            if path == "/api/v2/compliance/gdpr-export" and method == "GET":
                return await self._gdpr_export(query_params)

            # Audit verify endpoint
            if path == "/api/v2/compliance/audit-verify" and method == "POST":
                return await self._verify_audit(body)

            # Audit events endpoint (SIEM)
            if path == "/api/v2/compliance/audit-events" and method == "GET":
                return await self._get_audit_events(query_params)

            # GDPR Right-to-be-Forgotten endpoint
            if path == "/api/v2/compliance/gdpr/right-to-be-forgotten" and method == "POST":
                return await self._right_to_be_forgotten(body)

            # GDPR Deletion Management endpoints
            if path == "/api/v2/compliance/gdpr/deletions" and method == "GET":
                return await self._list_deletions(query_params)

            if path.startswith("/api/v2/compliance/gdpr/deletions/") and path.endswith("/cancel"):
                if method == "POST":
                    request_id = path.split("/")[-2]
                    return await self._cancel_deletion(request_id, body)

            if path.startswith("/api/v2/compliance/gdpr/deletions/") and method == "GET":
                request_id = path.split("/")[-1]
                return await self._get_deletion(request_id)

            # Legal Hold Management endpoints
            if path == "/api/v2/compliance/gdpr/legal-holds" and method == "GET":
                return await self._list_legal_holds(query_params)

            if path == "/api/v2/compliance/gdpr/legal-holds" and method == "POST":
                return await self._create_legal_hold(body, headers)

            if path.startswith("/api/v2/compliance/gdpr/legal-holds/") and method == "DELETE":
                hold_id = path.split("/")[-1]
                return await self._release_legal_hold(hold_id, body)

            # Coordinated deletion endpoint (backup-aware)
            if path == "/api/v2/compliance/gdpr/coordinated-deletion" and method == "POST":
                return await self._coordinated_deletion(body)

            # Execute pending deletions (for background job or manual trigger)
            if path == "/api/v2/compliance/gdpr/execute-pending" and method == "POST":
                return await self._execute_pending_deletions(body)

            # Backup exclusion management
            if path == "/api/v2/compliance/gdpr/backup-exclusions" and method == "GET":
                return await self._list_backup_exclusions(query_params)

            if path == "/api/v2/compliance/gdpr/backup-exclusions" and method == "POST":
                return await self._add_backup_exclusion(body)

            # =================================================================
            # CCPA Endpoints
            # =================================================================

            # CCPA Disclosure (Right to Know)
            if path == "/api/v2/compliance/ccpa/disclosure" and method == "GET":
                return await self._ccpa_disclosure(query_params)

            # CCPA Delete (Right to Delete)
            if path == "/api/v2/compliance/ccpa/delete" and method == "POST":
                return await self._ccpa_delete(body)

            # CCPA Opt-Out (Do Not Sell/Share)
            if path == "/api/v2/compliance/ccpa/opt-out" and method == "POST":
                return await self._ccpa_opt_out(body)

            # CCPA Correct (Right to Correct)
            if path == "/api/v2/compliance/ccpa/correct" and method == "POST":
                return await self._ccpa_correct(body)

            # CCPA Request Status
            if path == "/api/v2/compliance/ccpa/status" and method == "GET":
                return await self._ccpa_get_status(query_params)

            # =================================================================
            # HIPAA Endpoints
            # =================================================================

            # HIPAA Compliance Status
            if path == "/api/v2/compliance/hipaa/status" and method == "GET":
                return await self._hipaa_status(query_params)

            # HIPAA PHI Access Log
            if path == "/api/v2/compliance/hipaa/phi-access" and method == "GET":
                return await self._hipaa_phi_access_log(query_params)

            # HIPAA Breach Risk Assessment
            if path == "/api/v2/compliance/hipaa/breach-assessment" and method == "POST":
                return await self._hipaa_breach_assessment(body)

            # HIPAA BAA Management
            if path == "/api/v2/compliance/hipaa/baa" and method == "GET":
                return await self._hipaa_list_baas(query_params)

            if path == "/api/v2/compliance/hipaa/baa" and method == "POST":
                return await self._hipaa_create_baa(body)

            # HIPAA Security Rule Report
            if path == "/api/v2/compliance/hipaa/security-report" and method == "GET":
                return await self._hipaa_security_report(query_params)

            # HIPAA PHI De-identification
            if path == "/api/v2/compliance/hipaa/deidentify" and method == "POST":
                return await self._hipaa_deidentify(body)

            # HIPAA Safe Harbor Verification
            if path == "/api/v2/compliance/hipaa/safe-harbor/verify" and method == "POST":
                return await self._hipaa_safe_harbor_verify(body)

            # HIPAA PHI Detection
            if path == "/api/v2/compliance/hipaa/detect-phi" and method == "POST":
                return await self._hipaa_detect_phi(body)

            # =================================================================
            # EU AI Act Endpoints
            # =================================================================

            # EU AI Act Risk Classification
            if path == "/api/v2/compliance/eu-ai-act/classify" and method == "POST":
                return await self._eu_ai_act_classify(body)

            # EU AI Act Conformity Report (audit)
            if path == "/api/v2/compliance/eu-ai-act/audit" and method == "POST":
                return await self._eu_ai_act_audit(body)

            # EU AI Act Full Artifact Bundle Generation
            if path == "/api/v2/compliance/eu-ai-act/generate-bundle" and method == "POST":
                return await self._eu_ai_act_generate_bundle(body)

            return error_response("Not found", 404)

        except PermissionDeniedError as e:
            logger.warning("Permission denied for compliance request: %s", e)
            return error_response("Permission denied", 403)

        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            logger.exception("Error handling compliance request: %s", e)
            return error_response("Internal server error", 500)

    async def _get_rbac_coverage(self) -> "HandlerResult":
        """
        GET /api/v1/compliance/rbac-coverage

        Returns RBAC endpoint coverage metrics.

        Response shape:
            {"data": {"covered_endpoints": N, "total_endpoints": M, "coverage_pct": 87.5}}
        """
        from aragora.server.handlers.base import json_response

        try:
            from aragora.rbac.audit import compute_endpoint_coverage

            coverage = compute_endpoint_coverage()
        except (ImportError, RuntimeError, TypeError, ValueError, OSError) as exc:
            logger.warning("RBAC coverage scan failed, using fallback: %s", exc)
            coverage = {"covered_endpoints": 0, "total_endpoints": 0, "coverage_pct": 0.0}

        return json_response({"data": coverage})

    # Backward compatible timestamp parser (used in tests)
    _parse_timestamp = staticmethod(parse_timestamp)


def create_compliance_handler(server_context: dict[str, Any]) -> ComplianceHandler:
    """Factory function for handler registration."""
    return ComplianceHandler(server_context)


__all__ = ["ComplianceHandler", "create_compliance_handler"]
