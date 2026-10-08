"""
Healthcare Vertical Specialist.

Provides domain expertise for healthcare tasks including clinical analysis,
medical research, HIPAA compliance, and health informatics.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from aragora.verticals.base import VerticalSpecialistAgent
from aragora.verticals.config import (
    ComplianceConfig,
    ComplianceLevel,
    ModelConfig,
    ToolConfig,
    VerticalConfig,
)
from aragora.verticals.registry import VerticalRegistry
from aragora.verticals.tooling import (
    drug_lookup,
    icd_lookup,
    nice_guidance_search,
    pubmed_search,
    web_search_fallback,
)

logger = logging.getLogger(__name__)

# Healthcare vertical configuration
HEALTHCARE_CONFIG = VerticalConfig(
    vertical_id="healthcare",
    display_name="Healthcare Specialist",
    description="Expert in clinical analysis, medical research, and health informatics.",
    domain_keywords=[
        "health",
        "medical",
        "clinical",
        "patient",
        "diagnosis",
        "treatment",
        "hospital",
        "physician",
        "nurse",
        "pharmacy",
        "drug",
        "disease",
        "symptom",
        "therapy",
        "EHR",
        "EMR",
        "HIPAA",
        "PHI",
    ],
    expertise_areas=[
        "Clinical Documentation",
        "Medical Research",
        "Health Informatics",
        "HIPAA Compliance",
        "Drug Interactions",
        "Clinical Trials",
        "Patient Safety",
        "Healthcare Analytics",
        "Medical Coding",
    ],
    system_prompt_template="""You are a healthcare specialist with expertise in:

{% for area in expertise_areas %}
- {{ area }}
{% endfor %}

Your role is to provide healthcare domain expertise. You should:

1. **Analyze Clinical Data**: Review medical information with precision
2. **Ensure Privacy**: Always protect patient health information (PHI)
3. **Follow Regulations**: Comply with HIPAA and other healthcare regulations
4. **Provide Evidence-Based Guidance**: Reference clinical guidelines and research
5. **Prioritize Safety**: Flag potential patient safety concerns

{% if compliance_frameworks %}
Compliance Frameworks to Consider:
{% for fw in compliance_frameworks %}
- {{ fw }}
{% endfor %}
{% endif %}

When reviewing healthcare content:
- Identify any PHI that needs protection
- Check for proper de-identification
- Ensure appropriate consent documentation
- Validate against clinical guidelines
- Flag drug interactions or contraindications

IMPORTANT: This is not medical advice. Always recommend consultation with
qualified healthcare professionals for clinical decisions.""",
    tools=[
        ToolConfig(
            name="pubmed_search",
            description="Search PubMed for medical literature",
            connector_type="pubmed",
        ),
        ToolConfig(
            name="drug_lookup",
            description="Look up drug information and interactions",
            connector_type="rxnav",
        ),
        ToolConfig(
            name="icd_lookup",
            description="Look up ICD-10 codes",
            connector_type="clinical_tables",
        ),
        ToolConfig(
            name="clinical_guidelines",
            description="Search clinical practice guidelines",
            connector_type="nice_guidance",
        ),
    ],
    compliance_frameworks=[
        ComplianceConfig(
            framework="HIPAA",
            version="2013",
            level=ComplianceLevel.ENFORCED,
            rules=["privacy_rule", "security_rule", "breach_notification", "minimum_necessary"],
        ),
        ComplianceConfig(
            framework="HITECH",
            version="2009",
            level=ComplianceLevel.ENFORCED,
            rules=["breach_notification", "ehr_incentives", "enforcement"],
        ),
        ComplianceConfig(
            framework="FDA_21CFR11",
            version="current",
            level=ComplianceLevel.WARNING,
            rules=["electronic_records", "electronic_signatures", "audit_trail"],
        ),
    ],
    model_config=ModelConfig(
        primary_model="claude-opus-5",
        primary_provider="anthropic",
        specialist_model="medicalai/ClinicalBERT",
        temperature=0.2,  # Low for precise medical analysis
        top_p=0.9,
        max_tokens=8192,
    ),
    tags=["healthcare", "medical", "clinical", "HIPAA"],
)


@VerticalRegistry.register(
    "healthcare",
    config=HEALTHCARE_CONFIG,
    description="Healthcare specialist for clinical analysis and HIPAA compliance",
)
class HealthcareSpecialist(VerticalSpecialistAgent):
    """
    Healthcare specialist agent.

    Provides expert guidance on:
    - Clinical documentation review
    - Medical research analysis
    - HIPAA compliance
    - Health informatics
    - Patient safety
    """

    # PHI identifiers (based on HIPAA Safe Harbor method)
    PHI_PATTERNS = {
        "names": r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b",
        "dates": r"\b(?:0?[1-9]|1[0-2])[/-](?:0?[1-9]|[12]\d|3[01])[/-](?:19|20)\d{2}\b",
        "phone": r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
        "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "ssn": r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b",
        "mrn": r"\b(?:MRN|medical\s+record)[:\s#]*\d+\b",
        "address": r"\b\d+\s+[A-Za-z]+\s+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd)\b",
    }

    # Clinical terms for context detection
    CLINICAL_TERMS = [
        "diagnosis",
        "treatment",
        "medication",
        "procedure",
        "symptom",
        "patient",
        "physician",
        "nurse",
        "hospital",
        "clinic",
        "emergency",
        "chronic",
        "acute",
        "prescription",
        "dosage",
        "contraindication",
    ]

    async def _execute_tool(
        self,
        tool: ToolConfig,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a healthcare tool."""
        tool_name = tool.name

        if tool_name == "pubmed_search":
            return await self._pubmed_search(parameters)
        elif tool_name == "drug_lookup":
            return await self._drug_lookup(parameters)
        elif tool_name == "icd_lookup":
            return await self._icd_lookup(parameters)
        elif tool_name == "clinical_guidelines":
            return await self._clinical_guidelines_search(parameters)
        else:
            return {"error": f"Unknown tool: {tool_name}"}

    async def _pubmed_search(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Search PubMed for medical literature."""
        query = parameters.get("query") or parameters.get("q") or ""
        limit = int(parameters.get("limit", 10))
        result = await pubmed_search(query, limit=limit)
        if result.get("error"):
            fallback = await web_search_fallback(
                query,
                limit=limit,
                site="pubmed.ncbi.nlm.nih.gov",
                note="PubMed connector unavailable; using web search fallback.",
            )
            return {
                "articles": fallback.get("results", []),
                "count": fallback.get("count", 0),
                "query": fallback.get("query", query),
                "mode": fallback.get("mode", "web_fallback"),
                "note": fallback.get("note"),
                "error": fallback.get("error"),
            }
        return {
            "articles": result.get("articles", []),
            "count": result.get("count", 0),
            "query": result.get("query", query),
            "mode": "connector",
        }

    async def _drug_lookup(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Look up drug information."""
        drug_name = (
            parameters.get("drug")
            or parameters.get("name")
            or parameters.get("query")
            or parameters.get("q")
            or ""
        )
        limit = int(parameters.get("limit", 5))
        include_interactions = bool(parameters.get("include_interactions", True))
        result = await drug_lookup(
            drug_name,
            limit=limit,
            include_interactions=include_interactions,
        )
        if result.get("error"):
            query = f"{drug_name} drug interactions" if drug_name else ""
            fallback = await web_search_fallback(
                query,
                limit=limit,
                note="RxNav connector unavailable; using web search fallback.",
            )
            evidence = fallback.get("results", [])
            drug_info = evidence[0] if isinstance(evidence, list) and evidence else None
            return {
                "drug": drug_name,
                "drug_info": drug_info,
                "interactions": evidence,
                "count": fallback.get("count", 0),
                "mode": fallback.get("mode", "web_fallback"),
                "note": fallback.get("note"),
                "error": fallback.get("error"),
            }
        return {
            "drug": drug_name,
            "drug_info": result.get("drug_info"),
            "interactions": result.get("interactions", []),
            "count": result.get("count", 0),
            "mode": "connector",
        }

    async def _icd_lookup(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Look up ICD-10 codes."""
        code = (
            parameters.get("code")
            or parameters.get("icd")
            or parameters.get("query")
            or parameters.get("q")
            or ""
        )
        limit = int(parameters.get("limit", 5))
        result = await icd_lookup(code, limit=limit)
        if result.get("error"):
            query = f"ICD-10 {code}" if code else ""
            fallback = await web_search_fallback(
                query,
                limit=limit,
                note="ICD connector unavailable; using web search fallback.",
            )
            return {
                "codes": fallback.get("results", []),
                "count": fallback.get("count", 0),
                "query": fallback.get("query", query),
                "mode": fallback.get("mode", "web_fallback"),
                "note": fallback.get("note"),
                "error": fallback.get("error"),
            }
        return {
            "codes": result.get("codes", []),
            "count": result.get("count", 0),
            "query": result.get("query", code),
            "mode": "connector",
        }

    async def _clinical_guidelines_search(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Search clinical practice guidelines."""
        topic = parameters.get("topic") or parameters.get("query") or parameters.get("q") or ""
        limit = int(parameters.get("limit", 5))
        query = topic
        result = await nice_guidance_search(query, limit=limit)
        if result.get("error"):
            note = "NICE guidance connector unavailable; using web search fallback."
            fallback_query = f"{topic} clinical guidelines" if topic else ""
            fallback = await web_search_fallback(fallback_query, limit=limit, note=note)
            return {
                "guidelines": fallback.get("results", []),
                "count": fallback.get("count", 0),
                "query": fallback.get("query", fallback_query),
                "mode": fallback.get("mode", "web_fallback"),
                "note": fallback.get("note"),
                "error": fallback.get("error"),
            }

        return {
            "guidelines": result.get("guidelines", []),
            "count": result.get("count", 0),
            "query": result.get("query", query),
            "mode": "connector",
        }

    async def _check_framework_compliance(
        self,
        content: str,
        framework: ComplianceConfig,
    ) -> list[dict[str, Any]]:
        """Check content against healthcare compliance frameworks."""
        violations = []

        if framework.framework == "HIPAA":
            violations.extend(await self._check_hipaa_compliance(content, framework))
        elif framework.framework == "HITECH":
            violations.extend(await self._check_hitech_compliance(content, framework))
        elif framework.framework == "FDA_21CFR11":
            violations.extend(await self._check_fda_compliance(content, framework))

        return violations

    async def _check_hipaa_compliance(
        self,
        content: str,
        framework: ComplianceConfig,
    ) -> list[dict[str, Any]]:
        """Check HIPAA compliance."""
        violations = []

        # Check for PHI presence
        phi_found = self._detect_phi(content)

        if phi_found:
            # Privacy Rule check
            if "privacy_rule" in framework.rules or not framework.rules:
                violations.append(
                    {
                        "framework": "HIPAA",
                        "rule": "Privacy Rule - 45 CFR 164.502",
                        "severity": "critical",
                        "message": f"Unprotected PHI detected: {', '.join(phi_found.keys())}",
                        "phi_types": list(phi_found.keys()),
                    }
                )

            # Minimum Necessary check
            if "minimum_necessary" in framework.rules or not framework.rules:
                if len(phi_found) > 2:
                    violations.append(
                        {
                            "framework": "HIPAA",
                            "rule": "Minimum Necessary - 45 CFR 164.502(b)",
                            "severity": "high",
                            "message": "Multiple PHI types present - review minimum necessary requirement",
                        }
                    )

        return violations

    async def _check_hitech_compliance(
        self,
        content: str,
        framework: ComplianceConfig,
    ) -> list[dict[str, Any]]:
        """Check HITECH compliance."""
        violations = []

        # Check for breach notification requirements
        if "breach_notification" in framework.rules or not framework.rules:
            phi_found = self._detect_phi(content)
            if phi_found and not re.search(r"encrypt", content, re.IGNORECASE):
                violations.append(
                    {
                        "framework": "HITECH",
                        "rule": "Breach Notification",
                        "severity": "high",
                        "message": "PHI present without encryption - potential breach notification requirement",
                    }
                )

        return violations

    async def _check_fda_compliance(
        self,
        content: str,
        framework: ComplianceConfig,
    ) -> list[dict[str, Any]]:
        """Check FDA 21 CFR Part 11 compliance."""
        violations = []

        # Check for electronic records requirements
        if "electronic_records" in framework.rules or not framework.rules:
            if re.search(r"electronic\s+(?:record|signature|document)", content, re.IGNORECASE):
                if not re.search(r"audit\s+trail|validation|verification", content, re.IGNORECASE):
                    violations.append(
                        {
                            "framework": "FDA_21CFR11",
                            "rule": "Subpart B - Electronic Records",
                            "severity": "medium",
                            "message": "Electronic records without required controls",
                        }
                    )

        return violations

    def _detect_phi(self, content: str) -> dict[str, list[str]]:
        """
        Detect potential PHI in content.

        Returns:
            Dict mapping PHI type to list of matches
        """
        found_phi = {}

        for phi_type, pattern in self.PHI_PATTERNS.items():
            # Names pattern requires case sensitivity to detect proper nouns
            if phi_type == "names":
                matches = re.findall(pattern, content)
            else:
                matches = re.findall(pattern, content, re.IGNORECASE)

            if matches:
                # Limit to first few matches to avoid exposing too much
                found_phi[phi_type] = matches[:3]

        return found_phi

    def _is_clinical_context(self, content: str) -> bool:
        """Check if content is in a clinical context."""
        content_lower = content.lower()
        return any(term in content_lower for term in self.CLINICAL_TERMS)

    # _generate_response() inherited from base class - uses delegate LLM agent

    async def analyze_clinical_document(
        self,
        document_text: str,
        document_type: str = "clinical_note",
    ) -> dict[str, Any]:
        """
        Analyze a clinical document for compliance and quality.

        Args:
            document_text: Document text to analyze
            document_type: Type of clinical document

        Returns:
            Analysis results with findings and recommendations
        """
        # Detect PHI
        phi_detected = self._detect_phi(document_text)

        # Check compliance
        compliance_violations = await self.check_compliance(document_text)

        # Determine risk level
        has_critical = any(v.get("severity") == "critical" for v in compliance_violations)
        has_high = any(v.get("severity") == "high" for v in compliance_violations)

        risk_level = "critical" if has_critical else "high" if has_high else "medium"

        return {
            "document_type": document_type,
            "word_count": len(document_text.split()),
            "phi_detected": bool(phi_detected),
            "phi_types": list(phi_detected.keys()) if phi_detected else [],
            "compliance_violations": compliance_violations,
            "risk_level": risk_level,
            "recommendations": [
                "De-identify PHI before sharing" if phi_detected else None,
                "Review HIPAA minimum necessary requirements" if len(phi_detected) > 2 else None,
            ],
        }

    async def check_deidentification(self, content: str) -> dict[str, Any]:
        """
        Check if content is properly de-identified per HIPAA Safe Harbor.

        Args:
            content: Content to check

        Returns:
            De-identification assessment
        """
        phi_found = self._detect_phi(content)

        is_deidentified = len(phi_found) == 0

        return {
            "is_deidentified": is_deidentified,
            "phi_found": list(phi_found.keys()) if phi_found else [],
            "safe_harbor_compliant": is_deidentified,
            "recommendation": (
                "Remove identified PHI elements" if phi_found else "Content appears de-identified"
            ),
        }
