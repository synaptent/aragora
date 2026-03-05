"""
Compliance Namespace API

Provides methods for compliance and audit operations including
SOC 2 reporting, GDPR compliance, CCPA, HIPAA, EU AI Act, and
audit trail verification.

Features:
- SOC 2 Type II report generation
- GDPR data export and right-to-be-forgotten
- CCPA consumer rights
- HIPAA PHI access logging and breach assessment
- EU AI Act risk classification and artifact bundles
- Audit trail verification
- SIEM-compatible event export
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient

AuditEventType = Literal[
    "authentication",
    "authorization",
    "data_access",
    "data_modification",
    "admin_action",
    "compliance",
]


class ComplianceAPI:
    """
    Synchronous Compliance API.

    Provides methods for compliance and audit operations:
    - SOC 2 reporting
    - GDPR compliance
    - CCPA consumer rights
    - HIPAA compliance
    - EU AI Act compliance
    - Audit verification
    - Event export

    Example:
        >>> client = AragoraClient(base_url="https://api.aragora.ai", api_key="...")
        >>> status = client.compliance.get_status()
        >>> report = client.compliance.generate_soc2_report()
        >>> classification = client.compliance.eu_ai_act_classify("AI for hiring")
    """

    def __init__(self, client: AragoraClient):
        self._client = client

    # ===========================================================================
    # Compliance Status

    def get_status(self) -> dict[str, Any]:
        """Get overall compliance status."""
        return self._client.request("GET", "/api/v1/compliance/status")

    def get_summary(self) -> dict[str, Any]:
        """Get compliance summary."""
        return self._client.request("GET", "/api/v1/compliance/summary")

    def generate_soc2_report(self, **params: Any) -> dict[str, Any]:
        """Generate SOC 2 Type II compliance report."""
        return self._client.request("GET", "/api/v1/compliance/soc2-report", params=params)

    def get_audit_events(self, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        """Get compliance audit events."""
        return self._client.request(
            "GET", "/api/v1/compliance/audit-events", params={"limit": limit, "offset": offset}
        )

    def verify_audit(self, event_id: str | None = None) -> dict[str, Any]:
        """Verify audit trail integrity."""
        data: dict[str, Any] = {}
        if event_id:
            data["event_id"] = event_id
        return self._client.request("POST", "/api/v1/compliance/audit-verify", json=data)

    def gdpr_export(self, user_id: str | None = None, format: str = "json") -> dict[str, Any]:
        """Export GDPR-compliant data."""
        params: dict[str, Any] = {"format": format}
        if user_id:
            params["user_id"] = user_id
        return self._client.request("GET", "/api/v1/compliance/gdpr-export", params=params)

    def gdpr_right_to_be_forgotten(self, user_id: str, confirm: bool = True) -> dict[str, Any]:
        """Execute GDPR right to be forgotten."""
        return self._client.request(
            "POST",
            "/api/v1/compliance/gdpr/right-to-be-forgotten",
            json={"user_id": user_id, "confirm": confirm},
        )

    def validate_policies(self, policies: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Validate compliance policies."""
        data: dict[str, Any] = {}
        if policies:
            data["policies"] = policies
        return self._client.request("POST", "/api/v1/policies/validate", json=data)

    def get_violations(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Get policy violations."""
        return self._client.request(
            "GET", "/api/v1/policies/violations", params={"limit": limit, "offset": offset}
        )

    def check(self, **kwargs: Any) -> dict[str, Any]:
        """Run a compliance check against current configuration.

        Args:
            **kwargs: Check parameters (scope, frameworks, etc.)

        Returns:
            Compliance check results with pass/fail per framework.
        """
        return self._client.request("GET", "/api/v1/compliance/check", params=kwargs)

    def get_stats(self) -> dict[str, Any]:
        """Get compliance statistics (violation counts, trends, scores).

        Returns:
            Compliance statistics across all frameworks.
        """
        return self._client.request("GET", "/api/v1/compliance/stats")

    def get_violations_list(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Get compliance violations list.

        Args:
            limit: Maximum results.
            offset: Pagination offset.

        Returns:
            List of compliance violations.
        """
        return self._client.request(
            "GET",
            "/api/v1/compliance/violations",
            params={"limit": limit, "offset": offset},
        )

    def get_violation(self, violation_id: str) -> dict[str, Any]:
        """Get a compliance violation by ID.

        Args:
            violation_id: Violation identifier.

        Returns:
            Violation details.
        """
        return self._client.request("GET", f"/api/v1/compliance/violations/{violation_id}")

    def update_violation(
        self,
        violation_id: str,
        *,
        status: str | None = None,
        assigned_to: str | None = None,
        remediation_notes: str | None = None,
        due_date: str | None = None,
    ) -> dict[str, Any]:
        """Update a compliance violation.

        Args:
            violation_id: Violation identifier.
            status: New status (open, investigating, remediated, accepted).
            assigned_to: Assignee user ID or email.
            remediation_notes: Notes on remediation actions.
            due_date: Due date for remediation (ISO format).

        Returns:
            Updated violation details.
        """
        payload: dict[str, Any] = {}
        if status:
            payload["status"] = status
        if assigned_to:
            payload["assigned_to"] = assigned_to
        if remediation_notes:
            payload["remediation_notes"] = remediation_notes
        if due_date:
            payload["due_date"] = due_date
        return self._client.request(
            "PUT", f"/api/v1/compliance/violations/{violation_id}", json=payload
        )

    # ===========================================================================
    # EU AI Act

    def eu_ai_act_classify(self, description: str) -> dict[str, Any]:
        """Classify an AI use case by EU AI Act risk level.

        Args:
            description: Free-text description of the AI use case.

        Returns:
            Risk classification with level, rationale, and obligations.
        """
        return self._client.request(
            "POST",
            "/api/v2/compliance/eu-ai-act/classify",
            json={"description": description},
        )

    def eu_ai_act_audit(self, receipt: dict[str, Any]) -> dict[str, Any]:
        """Generate a conformity report from a decision receipt.

        Args:
            receipt: Decision receipt data.

        Returns:
            Conformity report with article-by-article assessment.
        """
        return self._client.request(
            "POST",
            "/api/v2/compliance/eu-ai-act/audit",
            json={"receipt": receipt},
        )

    def eu_ai_act_generate_bundle(
        self,
        receipt: dict[str, Any],
        *,
        provider_name: str | None = None,
        provider_contact: str | None = None,
        eu_representative: str | None = None,
        system_name: str | None = None,
        system_version: str | None = None,
    ) -> dict[str, Any]:
        """Generate a full EU AI Act compliance artifact bundle.

        Produces Articles 12 (Record-Keeping), 13 (Transparency), and
        14 (Human Oversight) artifacts bundled with a conformity report.

        Args:
            receipt: Decision receipt data.
            provider_name: Provider organization name.
            provider_contact: Provider contact email.
            eu_representative: EU representative name.
            system_name: AI system name.
            system_version: AI system version.

        Returns:
            Complete artifact bundle with integrity hash.
        """
        body: dict[str, Any] = {"receipt": receipt}
        if provider_name:
            body["provider_name"] = provider_name
        if provider_contact:
            body["provider_contact"] = provider_contact
        if eu_representative:
            body["eu_representative"] = eu_representative
        if system_name:
            body["system_name"] = system_name
        if system_version:
            body["system_version"] = system_version
        return self._client.request(
            "POST",
            "/api/v2/compliance/eu-ai-act/generate-bundle",
            json=body,
        )

    # ===========================================================================
    # HIPAA Compliance

    def hipaa_status(
        self, *, scope: str = "summary", include_recommendations: bool = True
    ) -> dict[str, Any]:
        """Get HIPAA compliance status overview.

        Args:
            scope: 'summary' or 'full' (includes safeguard details).
            include_recommendations: Include compliance recommendations.

        Returns:
            HIPAA compliance status with score, rules, and BAA summary.
        """
        return self._client.request(
            "GET",
            "/api/v2/compliance/hipaa/status",
            params={
                "scope": scope,
                "include_recommendations": str(include_recommendations).lower(),
            },
        )

    def hipaa_phi_access_log(
        self,
        *,
        patient_id: str | None = None,
        user_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Get PHI access log for audit purposes (45 CFR 164.312(b)).

        Args:
            patient_id: Filter by patient ID.
            user_id: Filter by accessing user.
            from_date: Start date (ISO format).
            to_date: End date (ISO format).
            limit: Max results (default 100, max 1000).

        Returns:
            PHI access log entries with filters applied.
        """
        params: dict[str, Any] = {"limit": str(limit)}
        if patient_id:
            params["patient_id"] = patient_id
        if user_id:
            params["user_id"] = user_id
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        return self._client.request("GET", "/api/v2/compliance/hipaa/phi-access", params=params)

    def hipaa_breach_assessment(
        self,
        incident_id: str,
        incident_type: str,
        *,
        phi_involved: bool = False,
        phi_types: list[str] | None = None,
        affected_individuals: int = 0,
        unauthorized_access: dict[str, Any] | None = None,
        mitigation_actions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Perform HIPAA breach risk assessment (45 CFR 164.402).

        Args:
            incident_id: Unique incident identifier.
            incident_type: Type of security incident.
            phi_involved: Whether PHI was involved.
            phi_types: Types of PHI involved.
            affected_individuals: Estimated number affected.
            unauthorized_access: Details of unauthorized access.
            mitigation_actions: Actions taken to mitigate.

        Returns:
            Breach assessment with risk factors and notification requirements.
        """
        body: dict[str, Any] = {
            "incident_id": incident_id,
            "incident_type": incident_type,
            "phi_involved": phi_involved,
            "affected_individuals": affected_individuals,
        }
        if phi_types:
            body["phi_types"] = phi_types
        if unauthorized_access:
            body["unauthorized_access"] = unauthorized_access
        if mitigation_actions:
            body["mitigation_actions"] = mitigation_actions
        return self._client.request("POST", "/api/v2/compliance/hipaa/breach-assessment", json=body)

    def hipaa_list_baas(self, *, status: str = "active", ba_type: str = "all") -> dict[str, Any]:
        """List Business Associate Agreements.

        Args:
            status: Filter by status (active, expired, pending, all).
            ba_type: Filter by BA type (vendor, subcontractor, all).

        Returns:
            List of BAAs with count and filters.
        """
        return self._client.request(
            "GET",
            "/api/v2/compliance/hipaa/baa",
            params={"status": status, "ba_type": ba_type},
        )

    def hipaa_create_baa(
        self,
        business_associate: str,
        ba_type: Literal["vendor", "subcontractor"],
        services_provided: str,
        *,
        phi_access_scope: list[str] | None = None,
        agreement_date: str | None = None,
        expiration_date: str | None = None,
        subcontractor_clause: bool = True,
    ) -> dict[str, Any]:
        """Register a new Business Associate Agreement.

        Args:
            business_associate: Name of the business associate.
            ba_type: 'vendor' or 'subcontractor'.
            services_provided: Description of services.
            phi_access_scope: Types of PHI access granted.
            agreement_date: Date of BAA execution (ISO format).
            expiration_date: BAA expiration date (ISO format).
            subcontractor_clause: Whether subcontractor clause is included.

        Returns:
            Created BAA record.
        """
        body: dict[str, Any] = {
            "business_associate": business_associate,
            "ba_type": ba_type,
            "services_provided": services_provided,
            "subcontractor_clause": subcontractor_clause,
        }
        if phi_access_scope:
            body["phi_access_scope"] = phi_access_scope
        if agreement_date:
            body["agreement_date"] = agreement_date
        if expiration_date:
            body["expiration_date"] = expiration_date
        return self._client.request("POST", "/api/v2/compliance/hipaa/baa", json=body)

    def hipaa_security_report(
        self, *, format: str = "json", include_evidence: bool = False
    ) -> dict[str, Any]:
        """Generate HIPAA Security Rule compliance report.

        Args:
            format: Output format ('json' or 'html').
            include_evidence: Include evidence references.

        Returns:
            HIPAA Security Rule compliance report.
        """
        return self._client.request(
            "GET",
            "/api/v2/compliance/hipaa/security-report",
            params={"format": format, "include_evidence": str(include_evidence).lower()},
        )

    def hipaa_deidentify(
        self,
        *,
        content: str | None = None,
        data: dict[str, Any] | None = None,
        method: str = "redact",
        identifier_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """De-identify content using HIPAA Safe Harbor method.

        Args:
            content: Text content to de-identify.
            data: Structured data dict to de-identify (alternative to content).
            method: Anonymization method (redact, hash, generalize, suppress, pseudonymize).
            identifier_types: Identifier types to target (default: all).

        Returns:
            Anonymization result with de-identified content and audit metadata.
        """
        body: dict[str, Any] = {"method": method}
        if content:
            body["content"] = content
        if data:
            body["data"] = data
        if identifier_types:
            body["identifier_types"] = identifier_types
        return self._client.request("POST", "/api/v2/compliance/hipaa/deidentify", json=body)

    def hipaa_safe_harbor_verify(self, content: str) -> dict[str, Any]:
        """Verify content meets HIPAA Safe Harbor requirements.

        Args:
            content: Text content to verify.

        Returns:
            Safe Harbor compliance result with identifiers remaining.
        """
        return self._client.request(
            "POST",
            "/api/v2/compliance/hipaa/safe-harbor/verify",
            json={"content": content},
        )

    def hipaa_detect_phi(self, content: str, *, min_confidence: float = 0.5) -> dict[str, Any]:
        """Detect HIPAA PHI identifiers in content.

        Args:
            content: Text content to scan.
            min_confidence: Minimum confidence threshold (default: 0.5).

        Returns:
            Detected identifiers with types, positions, and confidence scores.
        """
        return self._client.request(
            "POST",
            "/api/v2/compliance/hipaa/detect-phi",
            json={"content": content, "min_confidence": min_confidence},
        )

    def get_compliance_overview(self) -> dict[str, Any]:
        """Get compliance overview (v2).

        Returns:
            Dict with overall compliance status, scores, and framework summaries.
        """
        return self._client.request("GET", "/api/v1/compliance")

    def get_rbac_coverage(self) -> dict[str, Any]:
        """Get RBAC coverage report for compliance.

        Returns:
            Dict with RBAC coverage metrics and uncovered routes.
        """
        return self._client.request("GET", "/api/v1/compliance/rbac-coverage")


class AsyncComplianceAPI:
    """
    Asynchronous Compliance API.

    Example:
        >>> async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
        ...     status = await client.compliance.get_status()
        ...     classification = await client.compliance.eu_ai_act_classify("AI for hiring")
    """

    def __init__(self, client: AragoraAsyncClient):
        self._client = client

    # ===========================================================================
    # Compliance Status

    async def get_status(self) -> dict[str, Any]:
        """Get overall compliance status."""
        return await self._client.request("GET", "/api/v1/compliance/status")

    async def get_summary(self) -> dict[str, Any]:
        """Get compliance summary."""
        return await self._client.request("GET", "/api/v1/compliance/summary")

    async def generate_soc2_report(self, **params: Any) -> dict[str, Any]:
        """Generate SOC 2 Type II compliance report."""
        return await self._client.request("GET", "/api/v1/compliance/soc2-report", params=params)

    async def get_audit_events(self, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        """Get compliance audit events."""
        return await self._client.request(
            "GET", "/api/v1/compliance/audit-events", params={"limit": limit, "offset": offset}
        )

    async def verify_audit(self, event_id: str | None = None) -> dict[str, Any]:
        """Verify audit trail integrity."""
        data: dict[str, Any] = {}
        if event_id:
            data["event_id"] = event_id
        return await self._client.request("POST", "/api/v1/compliance/audit-verify", json=data)

    async def gdpr_export(self, user_id: str | None = None, format: str = "json") -> dict[str, Any]:
        """Export GDPR-compliant data."""
        params: dict[str, Any] = {"format": format}
        if user_id:
            params["user_id"] = user_id
        return await self._client.request("GET", "/api/v1/compliance/gdpr-export", params=params)

    async def gdpr_right_to_be_forgotten(
        self, user_id: str, confirm: bool = True
    ) -> dict[str, Any]:
        """Execute GDPR right to be forgotten."""
        return await self._client.request(
            "POST",
            "/api/v1/compliance/gdpr/right-to-be-forgotten",
            json={"user_id": user_id, "confirm": confirm},
        )

    async def validate_policies(
        self, policies: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Validate compliance policies."""
        data: dict[str, Any] = {}
        if policies:
            data["policies"] = policies
        return await self._client.request("POST", "/api/v1/policies/validate", json=data)

    async def get_violations(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Get policy violations."""
        return await self._client.request(
            "GET", "/api/v1/policies/violations", params={"limit": limit, "offset": offset}
        )

    async def check(self, **kwargs: Any) -> dict[str, Any]:
        """Run a compliance check against current configuration."""
        return await self._client.request("GET", "/api/v1/compliance/check", params=kwargs)

    async def get_stats(self) -> dict[str, Any]:
        """Get compliance statistics."""
        return await self._client.request("GET", "/api/v1/compliance/stats")

    async def get_violations_list(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Get compliance violations list."""
        return await self._client.request(
            "GET",
            "/api/v1/compliance/violations",
            params={"limit": limit, "offset": offset},
        )

    async def get_violation(self, violation_id: str) -> dict[str, Any]:
        """Get a compliance violation by ID."""
        return await self._client.request("GET", f"/api/v1/compliance/violations/{violation_id}")

    async def update_violation(
        self,
        violation_id: str,
        *,
        status: str | None = None,
        assigned_to: str | None = None,
        remediation_notes: str | None = None,
        due_date: str | None = None,
    ) -> dict[str, Any]:
        """Update a compliance violation."""
        payload: dict[str, Any] = {}
        if status:
            payload["status"] = status
        if assigned_to:
            payload["assigned_to"] = assigned_to
        if remediation_notes:
            payload["remediation_notes"] = remediation_notes
        if due_date:
            payload["due_date"] = due_date
        return await self._client.request(
            "PUT", f"/api/v1/compliance/violations/{violation_id}", json=payload
        )

    # ===========================================================================
    # EU AI Act

    async def eu_ai_act_classify(self, description: str) -> dict[str, Any]:
        """Classify an AI use case by EU AI Act risk level."""
        return await self._client.request(
            "POST",
            "/api/v2/compliance/eu-ai-act/classify",
            json={"description": description},
        )

    async def eu_ai_act_audit(self, receipt: dict[str, Any]) -> dict[str, Any]:
        """Generate a conformity report from a decision receipt."""
        return await self._client.request(
            "POST",
            "/api/v2/compliance/eu-ai-act/audit",
            json={"receipt": receipt},
        )

    async def eu_ai_act_generate_bundle(
        self,
        receipt: dict[str, Any],
        *,
        provider_name: str | None = None,
        provider_contact: str | None = None,
        eu_representative: str | None = None,
        system_name: str | None = None,
        system_version: str | None = None,
    ) -> dict[str, Any]:
        """Generate a full EU AI Act compliance artifact bundle."""
        body: dict[str, Any] = {"receipt": receipt}
        if provider_name:
            body["provider_name"] = provider_name
        if provider_contact:
            body["provider_contact"] = provider_contact
        if eu_representative:
            body["eu_representative"] = eu_representative
        if system_name:
            body["system_name"] = system_name
        if system_version:
            body["system_version"] = system_version
        return await self._client.request(
            "POST",
            "/api/v2/compliance/eu-ai-act/generate-bundle",
            json=body,
        )

    # ===========================================================================
    # HIPAA Compliance

    async def hipaa_status(
        self, *, scope: str = "summary", include_recommendations: bool = True
    ) -> dict[str, Any]:
        """Get HIPAA compliance status overview."""
        return await self._client.request(
            "GET",
            "/api/v2/compliance/hipaa/status",
            params={
                "scope": scope,
                "include_recommendations": str(include_recommendations).lower(),
            },
        )

    async def hipaa_phi_access_log(
        self,
        *,
        patient_id: str | None = None,
        user_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Get PHI access log for audit purposes (45 CFR 164.312(b))."""
        params: dict[str, Any] = {"limit": str(limit)}
        if patient_id:
            params["patient_id"] = patient_id
        if user_id:
            params["user_id"] = user_id
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        return await self._client.request(
            "GET", "/api/v2/compliance/hipaa/phi-access", params=params
        )

    async def hipaa_breach_assessment(
        self,
        incident_id: str,
        incident_type: str,
        *,
        phi_involved: bool = False,
        phi_types: list[str] | None = None,
        affected_individuals: int = 0,
        unauthorized_access: dict[str, Any] | None = None,
        mitigation_actions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Perform HIPAA breach risk assessment (45 CFR 164.402)."""
        body: dict[str, Any] = {
            "incident_id": incident_id,
            "incident_type": incident_type,
            "phi_involved": phi_involved,
            "affected_individuals": affected_individuals,
        }
        if phi_types:
            body["phi_types"] = phi_types
        if unauthorized_access:
            body["unauthorized_access"] = unauthorized_access
        if mitigation_actions:
            body["mitigation_actions"] = mitigation_actions
        return await self._client.request(
            "POST", "/api/v2/compliance/hipaa/breach-assessment", json=body
        )

    async def hipaa_list_baas(
        self, *, status: str = "active", ba_type: str = "all"
    ) -> dict[str, Any]:
        """List Business Associate Agreements."""
        return await self._client.request(
            "GET",
            "/api/v2/compliance/hipaa/baa",
            params={"status": status, "ba_type": ba_type},
        )

    async def hipaa_create_baa(
        self,
        business_associate: str,
        ba_type: Literal["vendor", "subcontractor"],
        services_provided: str,
        *,
        phi_access_scope: list[str] | None = None,
        agreement_date: str | None = None,
        expiration_date: str | None = None,
        subcontractor_clause: bool = True,
    ) -> dict[str, Any]:
        """Register a new Business Associate Agreement."""
        body: dict[str, Any] = {
            "business_associate": business_associate,
            "ba_type": ba_type,
            "services_provided": services_provided,
            "subcontractor_clause": subcontractor_clause,
        }
        if phi_access_scope:
            body["phi_access_scope"] = phi_access_scope
        if agreement_date:
            body["agreement_date"] = agreement_date
        if expiration_date:
            body["expiration_date"] = expiration_date
        return await self._client.request("POST", "/api/v2/compliance/hipaa/baa", json=body)

    async def hipaa_security_report(
        self, *, format: str = "json", include_evidence: bool = False
    ) -> dict[str, Any]:
        """Generate HIPAA Security Rule compliance report."""
        return await self._client.request(
            "GET",
            "/api/v2/compliance/hipaa/security-report",
            params={"format": format, "include_evidence": str(include_evidence).lower()},
        )

    async def hipaa_deidentify(
        self,
        *,
        content: str | None = None,
        data: dict[str, Any] | None = None,
        method: str = "redact",
        identifier_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """De-identify content using HIPAA Safe Harbor method."""
        body: dict[str, Any] = {"method": method}
        if content:
            body["content"] = content
        if data:
            body["data"] = data
        if identifier_types:
            body["identifier_types"] = identifier_types
        return await self._client.request("POST", "/api/v2/compliance/hipaa/deidentify", json=body)

    async def hipaa_safe_harbor_verify(self, content: str) -> dict[str, Any]:
        """Verify content meets HIPAA Safe Harbor requirements."""
        return await self._client.request(
            "POST",
            "/api/v2/compliance/hipaa/safe-harbor/verify",
            json={"content": content},
        )

    async def hipaa_detect_phi(
        self, content: str, *, min_confidence: float = 0.5
    ) -> dict[str, Any]:
        """Detect HIPAA PHI identifiers in content."""
        return await self._client.request(
            "POST",
            "/api/v2/compliance/hipaa/detect-phi",
            json={"content": content, "min_confidence": min_confidence},
        )

    async def get_compliance_overview(self) -> dict[str, Any]:
        """Get compliance overview (v2)."""
        return await self._client.request("GET", "/api/v1/compliance")

    async def get_rbac_coverage(self) -> dict[str, Any]:
        """Get RBAC coverage report for compliance."""
        return await self._client.request("GET", "/api/v1/compliance/rbac-coverage")
