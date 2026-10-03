"""
Legal Vertical Specialist.

Provides domain expertise for legal tasks including contract analysis,
compliance review, regulatory research, and legal document drafting.
"""

from __future__ import annotations

import logging
import os
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
    courtlistener_search,
    govinfo_search,
    lexis_search,
    web_search_fallback,
    westlaw_search,
)

logger = logging.getLogger(__name__)

# Legal vertical configuration
LEGAL_CONFIG = VerticalConfig(
    vertical_id="legal",
    display_name="Legal Specialist",
    description="Expert in contract analysis, compliance, and regulatory matters.",
    domain_keywords=[
        "contract",
        "legal",
        "law",
        "compliance",
        "regulation",
        "liability",
        "indemnification",
        "warranty",
        "terms",
        "agreement",
        "clause",
        "attorney",
        "counsel",
        "litigation",
        "dispute",
        "statute",
    ],
    expertise_areas=[
        "Contract Analysis",
        "Regulatory Compliance",
        "Risk Assessment",
        "Legal Research",
        "Document Review",
        "Due Diligence",
        "Privacy Law",
        "Intellectual Property",
        "Employment Law",
    ],
    system_prompt_template="""You are a legal specialist with expertise in:

{% for area in expertise_areas %}
- {{ area }}
{% endfor %}

Your role is to provide legal analysis and guidance. You should:

1. **Analyze Documents Carefully**: Review contracts and legal documents for risks and issues
2. **Identify Key Clauses**: Highlight important terms, obligations, and potential problems
3. **Assess Compliance**: Check against relevant regulations and standards
4. **Provide Recommendations**: Suggest improvements and flag concerns
5. **Cite Authorities**: Reference relevant laws, regulations, and precedents

{% if compliance_frameworks %}
Compliance Frameworks to Consider:
{% for fw in compliance_frameworks %}
- {{ fw }}
{% endfor %}
{% endif %}

When reviewing legal documents:
- Identify one-sided or unfavorable clauses
- Check for missing standard protections
- Assess liability and indemnification terms
- Review termination and renewal provisions
- Flag privacy and data protection issues

IMPORTANT: Clearly state that your analysis is for informational purposes only
and does not constitute legal advice. Recommend consultation with qualified
legal counsel for specific legal matters.""",
    tools=[
        ToolConfig(
            name="case_search",
            description="Search legal case databases",
            connector_type="courtlistener",
        ),
        ToolConfig(
            name="statute_lookup",
            description="Look up statutes and regulations",
            connector_type="govinfo",
        ),
        ToolConfig(
            name="contract_compare",
            description="Compare contract versions",
            connector_type="document",
        ),
    ],
    compliance_frameworks=[
        ComplianceConfig(
            framework="GDPR",
            version="2018",
            level=ComplianceLevel.WARNING,
            rules=["data_processing", "consent", "rights", "transfers", "breach"],
        ),
        ComplianceConfig(
            framework="CCPA",
            version="2020",
            level=ComplianceLevel.WARNING,
            rules=["disclosure", "opt_out", "deletion", "nondiscrimination"],
        ),
        ComplianceConfig(
            framework="HIPAA",
            version="2013",
            level=ComplianceLevel.ENFORCED,
            rules=["privacy", "security", "breach_notification"],
        ),
    ],
    model_config=ModelConfig(
        primary_model="claude-opus-5",
        primary_provider="anthropic",
        specialist_model="nlpaueb/legal-bert-base-uncased",
        temperature=0.2,  # Very low for precise legal analysis
        top_p=0.9,
        max_tokens=8192,
    ),
    tags=["legal", "contract", "compliance", "regulatory"],
)


@VerticalRegistry.register(
    "legal",
    config=LEGAL_CONFIG,
    description="Legal specialist for contract analysis and compliance review",
)
class LegalSpecialist(VerticalSpecialistAgent):
    """
    Legal specialist agent.

    Provides expert guidance on:
    - Contract analysis and review
    - Regulatory compliance
    - Legal research
    - Risk assessment
    - Due diligence
    """

    # Legal clause patterns
    CLAUSE_PATTERNS = {
        "indemnification": [
            r"indemnif(?:y|ication)",
            r"hold\s+harmless",
            r"defend\s+and\s+indemnify",
        ],
        "limitation_of_liability": [
            r"limit(?:ation)?\s+of\s+liability",
            r"in\s+no\s+event\s+shall",
            r"aggregate\s+liability",
        ],
        "termination": [
            r"terminat(?:e|ion)",
            r"right\s+to\s+cancel",
            r"upon\s+(?:\d+|thirty|sixty|ninety)\s+days?\s+notice",
        ],
        "confidentiality": [
            r"confidential(?:ity)?",
            r"non-disclosure",
            r"proprietary\s+information",
        ],
        "intellectual_property": [
            r"intellectual\s+property",
            r"patent|copyright|trademark",
            r"work\s+(?:made\s+)?for\s+hire",
        ],
    }

    async def _execute_tool(
        self,
        tool: ToolConfig,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a legal research tool."""
        tool_name = tool.name

        if tool_name == "case_search":
            return await self._case_search(parameters)
        elif tool_name == "statute_lookup":
            return await self._statute_lookup(parameters)
        elif tool_name == "contract_compare":
            return await self._contract_compare(parameters)
        else:
            return {"error": f"Unknown tool: {tool_name}"}

    async def _case_search(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Search legal case databases."""
        query = parameters.get("query") or parameters.get("q") or parameters.get("case") or ""
        jurisdiction = parameters.get("jurisdiction") or parameters.get("region") or ""
        limit = int(parameters.get("limit", 10))
        preferred = os.environ.get("ARAGORA_LEGAL_PRIMARY_SOURCE", "").strip().lower()

        premium_order = []
        if preferred in {"westlaw", "lexis"}:
            premium_order.append(preferred)
        for candidate in ("westlaw", "lexis"):
            if candidate not in premium_order:
                premium_order.append(candidate)

        for source in premium_order:
            if source == "westlaw":
                result = await westlaw_search(query, limit=limit)
            else:
                result = await lexis_search(query, limit=limit)
            if not result.get("error") and result.get("cases"):
                return {
                    "cases": result.get("cases", []),
                    "count": result.get("count", 0),
                    "query": result.get("query", query),
                    "mode": "connector",
                    "source": source,
                }

        result = await courtlistener_search(
            query,
            limit=limit,
            court=jurisdiction or None,
        )
        if result.get("error"):
            note = "Case law connectors unavailable; using web search fallback."
            search_query = f"{query} case law {jurisdiction}".strip()
            fallback = await web_search_fallback(search_query, limit=limit, note=note)
            return {
                "cases": fallback.get("results", []),
                "count": fallback.get("count", 0),
                "query": fallback.get("query", search_query),
                "mode": fallback.get("mode", "web_fallback"),
                "note": fallback.get("note"),
                "error": fallback.get("error"),
            }

        return {
            "cases": result.get("cases", []),
            "count": result.get("count", 0),
            "query": result.get("query", query),
            "mode": "connector",
            "court": result.get("court"),
            "source": "courtlistener",
        }

    async def _statute_lookup(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Look up statutes and regulations."""
        query = (
            parameters.get("query")
            or parameters.get("q")
            or parameters.get("statute")
            or parameters.get("citation")
            or ""
        )
        jurisdiction = parameters.get("jurisdiction") or parameters.get("region") or ""
        limit = int(parameters.get("limit", 10))
        collection = parameters.get("collection") or "USCODE"
        result = await govinfo_search(
            query,
            limit=limit,
            collection=collection,
        )
        if result.get("error"):
            note = "GovInfo connector unavailable; using web search fallback."
            search_query = f"{query} statute {jurisdiction}".strip()
            fallback = await web_search_fallback(search_query, limit=limit, note=note)
            return {
                "statutes": fallback.get("results", []),
                "count": fallback.get("count", 0),
                "query": fallback.get("query", search_query),
                "mode": fallback.get("mode", "web_fallback"),
                "note": fallback.get("note"),
                "error": fallback.get("error"),
            }

        return {
            "statutes": result.get("results", []),
            "count": result.get("count", 0),
            "query": result.get("query", query),
            "mode": "connector",
            "collection": result.get("collection"),
        }

    async def _contract_compare(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Compare contract versions."""
        import difflib

        left = (
            parameters.get("left")
            or parameters.get("contract_a")
            or parameters.get("version_a")
            or parameters.get("text_a")
            or ""
        )
        right = (
            parameters.get("right")
            or parameters.get("contract_b")
            or parameters.get("version_b")
            or parameters.get("text_b")
            or ""
        )
        if not left or not right:
            return {"differences": [], "error": "contract_a and contract_b are required"}

        from_label = parameters.get("from_label", "contract_a")
        to_label = parameters.get("to_label", "contract_b")
        max_lines = int(parameters.get("limit", 200))

        diff_lines = list(
            difflib.unified_diff(
                left.splitlines(),
                right.splitlines(),
                fromfile=from_label,
                tofile=to_label,
                lineterm="",
            )
        )
        added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
        removed = sum(
            1 for line in diff_lines if line.startswith("-") and not line.startswith("---")
        )

        truncated = len(diff_lines) > max_lines
        return {
            "differences": diff_lines[:max_lines],
            "truncated": truncated,
            "total_lines": len(diff_lines),
            "summary": {"added": added, "removed": removed},
        }

    async def _check_framework_compliance(
        self,
        content: str,
        framework: ComplianceConfig,
    ) -> list[dict[str, Any]]:
        """Check document against legal compliance frameworks."""
        violations = []

        if framework.framework == "GDPR":
            violations.extend(await self._check_gdpr_compliance(content, framework))
        elif framework.framework == "CCPA":
            violations.extend(await self._check_ccpa_compliance(content, framework))
        elif framework.framework == "HIPAA":
            violations.extend(await self._check_hipaa_compliance(content, framework))

        return violations

    async def _check_gdpr_compliance(
        self,
        content: str,
        framework: ComplianceConfig,
    ) -> list[dict[str, Any]]:
        """Check GDPR compliance."""
        violations = []
        content_lower = content.lower()

        # Check for data processing provisions
        if "data_processing" in framework.rules or not framework.rules:
            if not re.search(r"lawful\s+basis|legal\s+basis|consent", content_lower):
                violations.append(
                    {
                        "framework": "GDPR",
                        "rule": "Article 6 - Lawful Basis",
                        "severity": "high",
                        "message": "Missing specification of lawful basis for data processing",
                    }
                )

        # Check for consent requirements
        if "consent" in framework.rules or not framework.rules:
            if re.search(r"personal\s+data|pii", content_lower):
                if not re.search(r"consent|opt.?in", content_lower):
                    violations.append(
                        {
                            "framework": "GDPR",
                            "rule": "Article 7 - Consent",
                            "severity": "medium",
                            "message": "Personal data processing without clear consent provisions",
                        }
                    )

        # Check for data subject rights
        if "rights" in framework.rules or not framework.rules:
            rights_terms = ["right to access", "right to erasure", "data portability"]
            if not any(term in content_lower for term in rights_terms):
                violations.append(
                    {
                        "framework": "GDPR",
                        "rule": "Chapter III - Rights of Data Subject",
                        "severity": "medium",
                        "message": "Missing data subject rights provisions",
                    }
                )

        return violations

    async def _check_ccpa_compliance(
        self,
        content: str,
        framework: ComplianceConfig,
    ) -> list[dict[str, Any]]:
        """Check CCPA compliance."""
        violations = []
        content_lower = content.lower()

        # Check for disclosure requirements
        if "disclosure" in framework.rules or not framework.rules:
            if re.search(r"personal\s+information|consumer\s+data", content_lower):
                if not re.search(r"categories\s+of\s+personal\s+information", content_lower):
                    violations.append(
                        {
                            "framework": "CCPA",
                            "rule": "Section 1798.100 - Disclosure",
                            "severity": "medium",
                            "message": "Missing disclosure of personal information categories",
                        }
                    )

        # Check for opt-out provisions
        if "opt_out" in framework.rules or not framework.rules:
            if re.search(r"sell|share.*personal", content_lower):
                if not re.search(r"opt.?out|do\s+not\s+sell", content_lower):
                    violations.append(
                        {
                            "framework": "CCPA",
                            "rule": "Section 1798.120 - Opt-Out",
                            "severity": "high",
                            "message": "Missing opt-out right for sale of personal information",
                        }
                    )

        return violations

    async def _check_hipaa_compliance(
        self,
        content: str,
        framework: ComplianceConfig,
    ) -> list[dict[str, Any]]:
        """Check HIPAA compliance."""
        violations = []
        content_lower = content.lower()

        # Check for PHI references without protections
        phi_terms = ["health information", "medical record", "patient data", "phi"]
        if any(term in content_lower for term in phi_terms):
            # Check for required protections
            if "privacy" in framework.rules or not framework.rules:
                if not re.search(r"privacy\s+(?:rule|notice|practices)", content_lower):
                    violations.append(
                        {
                            "framework": "HIPAA",
                            "rule": "Privacy Rule",
                            "severity": "high",
                            "message": "PHI referenced without privacy rule compliance",
                        }
                    )

            if "security" in framework.rules or not framework.rules:
                if not re.search(r"safeguard|encrypt|security\s+measure", content_lower):
                    violations.append(
                        {
                            "framework": "HIPAA",
                            "rule": "Security Rule",
                            "severity": "high",
                            "message": "PHI referenced without security safeguards",
                        }
                    )

        return violations

    # _generate_response() inherited from base class - uses delegate LLM agent

    async def analyze_contract(
        self,
        contract_text: str,
        focus_areas: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Analyze a contract for risks and issues.

        Args:
            contract_text: Contract text to analyze
            focus_areas: Specific areas to focus on

        Returns:
            Analysis results with findings and recommendations
        """
        focus = focus_areas or list(self.CLAUSE_PATTERNS.keys())

        # Find clauses
        found_clauses = {}
        for clause_type, patterns in self.CLAUSE_PATTERNS.items():
            if clause_type in focus:
                for pattern in patterns:
                    if re.search(pattern, contract_text, re.IGNORECASE):
                        found_clauses[clause_type] = True
                        break
                else:
                    found_clauses[clause_type] = False

        # Check compliance
        compliance_violations = await self.check_compliance(contract_text)

        # Identify missing clauses
        missing_clauses = [c for c, found in found_clauses.items() if not found]

        return {
            "word_count": len(contract_text.split()),
            "found_clauses": [c for c, found in found_clauses.items() if found],
            "missing_clauses": missing_clauses,
            "compliance_violations": compliance_violations,
            "risk_level": "high" if len(missing_clauses) > 2 or compliance_violations else "medium",
            "recommendations": [],
        }
