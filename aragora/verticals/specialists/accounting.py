"""
Accounting Vertical Specialist.

Provides domain expertise for accounting and finance tasks including
financial analysis, audit review, SOX compliance, and tax matters.
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
    gaap_lookup,
    sec_filings_search,
    tax_reference_search,
    web_search_fallback,
)

logger = logging.getLogger(__name__)

# Accounting vertical configuration
ACCOUNTING_CONFIG = VerticalConfig(
    vertical_id="accounting",
    display_name="Accounting & Finance Specialist",
    description="Expert in financial analysis, audit, compliance, and accounting standards.",
    domain_keywords=[
        "accounting",
        "finance",
        "audit",
        "tax",
        "financial",
        "revenue",
        "expense",
        "balance sheet",
        "income statement",
        "cash flow",
        "GAAP",
        "IFRS",
        "SOX",
        "internal control",
        "journal entry",
        "depreciation",
        "amortization",
        "accrual",
        "reconciliation",
    ],
    expertise_areas=[
        "Financial Statement Analysis",
        "Audit & Assurance",
        "SOX Compliance",
        "Tax Planning",
        "Internal Controls",
        "Revenue Recognition",
        "Cost Accounting",
        "Financial Reporting",
        "Regulatory Compliance",
    ],
    system_prompt_template="""You are an accounting and finance specialist with expertise in:

{% for area in expertise_areas %}
- {{ area }}
{% endfor %}

Your role is to provide expert financial and accounting guidance. You should:

1. **Analyze Financial Data**: Review financial statements and transactions accurately
2. **Ensure Compliance**: Check against GAAP, IFRS, SOX, and other standards
3. **Identify Risks**: Flag potential issues, fraud indicators, and control weaknesses
4. **Apply Standards**: Reference relevant accounting standards and regulations
5. **Provide Clear Explanations**: Make complex financial concepts understandable

{% if compliance_frameworks %}
Compliance Frameworks to Consider:
{% for fw in compliance_frameworks %}
- {{ fw }}
{% endfor %}
{% endif %}

When reviewing financial information:
- Verify calculations and mathematical accuracy
- Check for proper revenue recognition
- Ensure adequate internal controls
- Identify unusual transactions or patterns
- Review for proper disclosure requirements

IMPORTANT: This analysis is for informational purposes only. Recommend
consultation with qualified accounting professionals for specific matters.""",
    tools=[
        ToolConfig(
            name="sec_filings",
            description="Search SEC filings and documents",
            connector_type="sec",
        ),
        ToolConfig(
            name="gaap_lookup",
            description="Look up GAAP accounting standards",
            connector_type="fasb",
        ),
        ToolConfig(
            name="ratio_calculator",
            description="Calculate financial ratios",
            connector_type="calculation",
        ),
        ToolConfig(
            name="tax_reference",
            description="Look up tax regulations and rates",
            connector_type="irs",
        ),
    ],
    compliance_frameworks=[
        ComplianceConfig(
            framework="SOX",
            version="2002",
            level=ComplianceLevel.ENFORCED,
            rules=["section_302", "section_404", "section_802", "section_906"],
        ),
        ComplianceConfig(
            framework="GAAP",
            version="current",
            level=ComplianceLevel.ENFORCED,
            rules=["revenue_recognition", "fair_value", "leases", "disclosure"],
        ),
        ComplianceConfig(
            framework="PCAOB",
            version="current",
            level=ComplianceLevel.WARNING,
            rules=["AS2201", "AS3101", "AS2110"],
        ),
    ],
    model_config=ModelConfig(
        primary_model="claude-opus-5",
        primary_provider="anthropic",
        specialist_model="ProsusAI/finbert",
        temperature=0.1,  # Very low for precise financial analysis
        top_p=0.9,
        max_tokens=8192,
    ),
    tags=["accounting", "finance", "audit", "SOX", "GAAP"],
)


@VerticalRegistry.register(
    "accounting",
    config=ACCOUNTING_CONFIG,
    description="Accounting specialist for financial analysis and SOX compliance",
)
class AccountingSpecialist(VerticalSpecialistAgent):
    """
    Accounting and finance specialist agent.

    Provides expert guidance on:
    - Financial statement analysis
    - Audit and assurance
    - SOX compliance
    - Internal controls
    - Regulatory compliance
    """

    # Financial statement patterns
    FINANCIAL_PATTERNS = {
        "revenue_recognition": [
            r"revenue\s+recogn(?:ition|ized)",
            r"deferred\s+revenue",
            r"unbilled\s+revenue",
            r"ASC\s+606",
        ],
        "internal_control": [
            r"internal\s+control",
            r"segregation\s+of\s+duties",
            r"authorization",
            r"reconciliation",
        ],
        "material_weakness": [
            r"material\s+weakness",
            r"significant\s+deficiency",
            r"control\s+deficiency",
        ],
        "fraud_indicators": [
            r"override|circumvent",
            r"unusual\s+(?:transaction|entry|adjustment)",
            r"significant\s+related\s+party",
            r"aggressive\s+accounting",
        ],
    }

    # Financial ratios for analysis
    RATIO_FORMULAS = {
        "current_ratio": "current_assets / current_liabilities",
        "quick_ratio": "(current_assets - inventory) / current_liabilities",
        "debt_to_equity": "total_debt / total_equity",
        "gross_margin": "(revenue - cogs) / revenue",
        "net_margin": "net_income / revenue",
        "return_on_equity": "net_income / shareholders_equity",
    }

    async def _execute_tool(
        self,
        tool: ToolConfig,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute an accounting tool."""
        tool_name = tool.name

        if tool_name == "sec_filings":
            return await self._sec_filings_search(parameters)
        elif tool_name == "gaap_lookup":
            return await self._gaap_lookup(parameters)
        elif tool_name == "ratio_calculator":
            return await self._calculate_ratios(parameters)
        elif tool_name == "tax_reference":
            return await self._tax_reference(parameters)
        else:
            return {"error": f"Unknown tool: {tool_name}"}

    async def _sec_filings_search(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Search SEC filings."""
        query = (
            parameters.get("query")
            or parameters.get("ticker")
            or parameters.get("cik")
            or parameters.get("company")
            or ""
        )
        limit = int(parameters.get("limit", 10))
        form_type = parameters.get("form_type") or parameters.get("form")
        date_from = parameters.get("date_from")
        date_to = parameters.get("date_to")
        return await sec_filings_search(
            query,
            limit=limit,
            form_type=form_type,
            date_from=date_from,
            date_to=date_to,
        )

    async def _gaap_lookup(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Look up GAAP standards."""
        topic = parameters.get("topic") or parameters.get("query") or parameters.get("q") or ""
        limit = int(parameters.get("limit", 5))
        result = await gaap_lookup(topic, limit=limit)
        if result.get("error"):
            note = "FASB connector unavailable; using web search fallback."
            query = f"{topic} GAAP standard" if topic else ""
            fallback = await web_search_fallback(query, limit=limit, note=note)
            return {
                "standards": fallback.get("results", []),
                "count": fallback.get("count", 0),
                "query": fallback.get("query", query),
                "mode": fallback.get("mode", "web_fallback"),
                "note": fallback.get("note"),
                "error": fallback.get("error"),
            }
        return {
            "standards": result.get("standards", []),
            "count": result.get("count", 0),
            "query": result.get("query", topic),
            "mode": "connector",
        }

    async def _calculate_ratios(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Calculate financial ratios."""
        ratios = {}

        # Extract financial data from parameters
        current_assets = parameters.get("current_assets", 0)
        current_liabilities = parameters.get("current_liabilities", 0)
        inventory = parameters.get("inventory", 0)
        total_debt = parameters.get("total_debt", 0)
        total_equity = parameters.get("total_equity", 0)
        revenue = parameters.get("revenue", 0)
        cogs = parameters.get("cogs", 0)
        net_income = parameters.get("net_income", 0)

        # Calculate ratios (with zero division protection)
        if current_liabilities > 0:
            ratios["current_ratio"] = current_assets / current_liabilities
            ratios["quick_ratio"] = (current_assets - inventory) / current_liabilities

        if total_equity > 0:
            ratios["debt_to_equity"] = total_debt / total_equity
            ratios["return_on_equity"] = net_income / total_equity

        if revenue > 0:
            ratios["gross_margin"] = (revenue - cogs) / revenue
            ratios["net_margin"] = net_income / revenue

        return {"ratios": ratios}

    async def _tax_reference(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Look up tax regulations."""
        topic = parameters.get("topic") or parameters.get("query") or parameters.get("q") or ""
        jurisdiction = parameters.get("jurisdiction") or parameters.get("region") or ""
        limit = int(parameters.get("limit", 5))
        result = await tax_reference_search(
            topic,
            limit=limit,
            jurisdiction=jurisdiction or "US",
        )
        if result.get("error"):
            note = "IRS connector unavailable; using web search fallback."
            query = f"{topic} tax regulation {jurisdiction}".strip()
            fallback = await web_search_fallback(query, limit=limit, note=note)
            return {
                "regulations": fallback.get("results", []),
                "count": fallback.get("count", 0),
                "query": fallback.get("query", query),
                "mode": fallback.get("mode", "web_fallback"),
                "note": fallback.get("note"),
                "error": fallback.get("error"),
            }

        return {
            "regulations": result.get("results", []),
            "count": result.get("count", 0),
            "query": result.get("query", topic),
            "mode": "connector",
            "jurisdiction": result.get("jurisdiction"),
            "connector": result.get("connector"),
        }

    async def _check_framework_compliance(
        self,
        content: str,
        framework: ComplianceConfig,
    ) -> list[dict[str, Any]]:
        """Check content against accounting compliance frameworks."""
        violations = []

        if framework.framework == "SOX":
            violations.extend(await self._check_sox_compliance(content, framework))
        elif framework.framework == "GAAP":
            violations.extend(await self._check_gaap_compliance(content, framework))
        elif framework.framework == "PCAOB":
            violations.extend(await self._check_pcaob_compliance(content, framework))

        return violations

    async def _check_sox_compliance(
        self,
        content: str,
        framework: ComplianceConfig,
    ) -> list[dict[str, Any]]:
        """Check SOX compliance."""
        violations = []
        content_lower = content.lower()

        # Section 302 - CEO/CFO certifications
        if "section_302" in framework.rules or not framework.rules:
            if re.search(
                r"financial\s+statement|quarterly\s+report|annual\s+report", content_lower
            ):
                if not re.search(r"certif(?:y|ication)|attest", content_lower):
                    violations.append(
                        {
                            "framework": "SOX",
                            "rule": "Section 302 - Certification",
                            "severity": "high",
                            "message": "Financial statement without management certification reference",
                        }
                    )

        # Section 404 - Internal control assessment
        if "section_404" in framework.rules or not framework.rules:
            # Check for control deficiency indicators
            for pattern in self.FINANCIAL_PATTERNS.get("material_weakness", []):
                if re.search(pattern, content, re.IGNORECASE):
                    violations.append(
                        {
                            "framework": "SOX",
                            "rule": "Section 404 - Internal Controls",
                            "severity": "critical",
                            "message": "Material weakness or control deficiency indicated",
                        }
                    )
                    break

        # Section 802 - Record retention
        if "section_802" in framework.rules or not framework.rules:
            if re.search(r"destro(?:y|yed)|delet(?:e|ed)|shred", content_lower):
                if re.search(r"audit|work\s*paper|financial\s+record", content_lower):
                    violations.append(
                        {
                            "framework": "SOX",
                            "rule": "Section 802 - Record Retention",
                            "severity": "critical",
                            "message": "Potential destruction of audit-related records",
                        }
                    )

        return violations

    async def _check_gaap_compliance(
        self,
        content: str,
        framework: ComplianceConfig,
    ) -> list[dict[str, Any]]:
        """Check GAAP compliance."""
        violations = []
        content_lower = content.lower()

        # Revenue recognition (ASC 606)
        if "revenue_recognition" in framework.rules or not framework.rules:
            if re.search(r"revenue|sales|income", content_lower):
                if not re.search(
                    r"recogni(?:ze|tion)|ASC\s*606|contract|performance\s+obligation", content_lower
                ):
                    violations.append(
                        {
                            "framework": "GAAP",
                            "rule": "ASC 606 - Revenue Recognition",
                            "severity": "medium",
                            "message": "Revenue discussed without clear recognition criteria",
                        }
                    )

        # Fair value measurement
        if "fair_value" in framework.rules or not framework.rules:
            if re.search(r"fair\s+value|market\s+value", content_lower):
                if not re.search(r"level\s+[123]|observable|unobservable|input", content_lower):
                    violations.append(
                        {
                            "framework": "GAAP",
                            "rule": "ASC 820 - Fair Value",
                            "severity": "low",
                            "message": "Fair value reference without hierarchy level indication",
                        }
                    )

        return violations

    async def _check_pcaob_compliance(
        self,
        content: str,
        framework: ComplianceConfig,
    ) -> list[dict[str, Any]]:
        """Check PCAOB auditing standards compliance."""
        violations = []

        # AS 2201 - ICFR Audit
        if "AS2201" in framework.rules or not framework.rules:
            if re.search(r"internal\s+control.*audit", content, re.IGNORECASE):
                if not re.search(
                    r"material\s+weakness|significant\s+deficiency|test.*control",
                    content,
                    re.IGNORECASE,
                ):
                    violations.append(
                        {
                            "framework": "PCAOB",
                            "rule": "AS 2201 - ICFR Audit",
                            "severity": "medium",
                            "message": "Internal control audit without deficiency assessment",
                        }
                    )

        return violations

    # _generate_response() inherited from base class - uses delegate LLM agent

    async def analyze_financial_statement(
        self,
        statement_text: str,
        statement_type: str = "balance_sheet",
    ) -> dict[str, Any]:
        """
        Analyze a financial statement for compliance and issues.

        Args:
            statement_text: Statement text to analyze
            statement_type: Type of statement (balance_sheet, income_statement, cash_flow)

        Returns:
            Analysis results with findings and recommendations
        """
        # Check for key patterns
        found_patterns = {}
        for category, patterns in self.FINANCIAL_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, statement_text, re.IGNORECASE):
                    found_patterns[category] = True
                    break

        # Check compliance
        compliance_violations = await self.check_compliance(statement_text)

        # Identify fraud indicators
        fraud_risks = []
        for pattern in self.FINANCIAL_PATTERNS.get("fraud_indicators", []):
            if re.search(pattern, statement_text, re.IGNORECASE):
                fraud_risks.append(pattern)

        return {
            "statement_type": statement_type,
            "compliance_violations": compliance_violations,
            "patterns_found": list(found_patterns.keys()),
            "fraud_risk_indicators": fraud_risks,
            "risk_level": "high" if fraud_risks or compliance_violations else "low",
            "recommendations": [],
        }

    async def review_internal_controls(
        self,
        control_description: str,
    ) -> dict[str, Any]:
        """
        Review internal control documentation.

        Args:
            control_description: Description of internal controls

        Returns:
            Review results with findings
        """
        control_elements = {
            "segregation_of_duties": bool(
                re.search(r"segregat|separate\s+dut", control_description, re.IGNORECASE)
            ),
            "authorization": bool(
                re.search(r"authoriz|approv", control_description, re.IGNORECASE)
            ),
            "reconciliation": bool(
                re.search(r"reconcil|verify|match", control_description, re.IGNORECASE)
            ),
            "documentation": bool(
                re.search(r"document|record|log", control_description, re.IGNORECASE)
            ),
            "monitoring": bool(
                re.search(r"monitor|review|oversee", control_description, re.IGNORECASE)
            ),
        }

        missing_elements = [k for k, v in control_elements.items() if not v]

        return {
            "control_elements": control_elements,
            "missing_elements": missing_elements,
            "control_rating": "adequate" if len(missing_elements) <= 1 else "needs_improvement",
            "recommendations": [f"Consider adding {elem} controls" for elem in missing_elements],
        }
