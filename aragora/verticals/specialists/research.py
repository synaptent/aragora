"""
Research Vertical Specialist.

Provides domain expertise for research tasks including literature review,
methodology analysis, statistical review, and scientific writing.
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
    arxiv_search,
    crossref_lookup,
    pubmed_search,
    semantic_scholar_search,
    web_search_fallback,
)

logger = logging.getLogger(__name__)

# Research vertical configuration
RESEARCH_CONFIG = VerticalConfig(
    vertical_id="research",
    display_name="Research Specialist",
    description="Expert in research methodology, literature analysis, and scientific writing.",
    domain_keywords=[
        "research",
        "study",
        "experiment",
        "hypothesis",
        "methodology",
        "statistical",
        "data",
        "analysis",
        "sample",
        "results",
        "peer review",
        "publication",
        "citation",
        "literature",
        "IRB",
        "ethics",
        "protocol",
        "findings",
        "conclusion",
    ],
    expertise_areas=[
        "Literature Review",
        "Research Methodology",
        "Statistical Analysis",
        "Scientific Writing",
        "Peer Review",
        "Research Ethics",
        "Data Analysis",
        "Citation Analysis",
        "Meta-Analysis",
    ],
    system_prompt_template="""You are a research specialist with expertise in:

{% for area in expertise_areas %}
- {{ area }}
{% endfor %}

Your role is to provide expert research guidance. You should:

1. **Evaluate Methodology**: Assess research design, sampling, and validity
2. **Analyze Statistics**: Review statistical methods and interpretation
3. **Check Citations**: Verify proper citation and literature coverage
4. **Ensure Ethics**: Flag ethical concerns and compliance issues
5. **Improve Quality**: Suggest improvements for rigor and clarity

{% if compliance_frameworks %}
Compliance Frameworks to Consider:
{% for fw in compliance_frameworks %}
- {{ fw }}
{% endfor %}
{% endif %}

When reviewing research:
- Assess the research design and methodology
- Check for appropriate statistical analysis
- Verify proper citation practices
- Identify potential biases or limitations
- Ensure ethical compliance (IRB, informed consent)

Provide constructive, evidence-based feedback that helps researchers
improve the quality and rigor of their work.""",
    tools=[
        ToolConfig(
            name="arxiv_search",
            description="Search arXiv for preprints",
            connector_type="arxiv",
        ),
        ToolConfig(
            name="pubmed_search",
            description="Search PubMed for medical literature",
            connector_type="pubmed",
        ),
        ToolConfig(
            name="semantic_scholar",
            description="Search Semantic Scholar for papers",
            connector_type="semantic_scholar",
        ),
        ToolConfig(
            name="citation_check",
            description="Verify citations and check for retractions",
            connector_type="crossref",
        ),
    ],
    compliance_frameworks=[
        ComplianceConfig(
            framework="IRB",
            version="current",
            level=ComplianceLevel.ENFORCED,
            rules=["informed_consent", "minimal_risk", "privacy", "vulnerable_populations"],
        ),
        ComplianceConfig(
            framework="CONSORT",
            version="2010",
            level=ComplianceLevel.WARNING,
            rules=["randomization", "blinding", "outcomes", "sample_size", "flow_diagram"],
        ),
        ComplianceConfig(
            framework="PRISMA",
            version="2020",
            level=ComplianceLevel.WARNING,
            rules=["search_strategy", "selection", "synthesis", "bias_assessment"],
        ),
    ],
    model_config=ModelConfig(
        primary_model="claude-opus-5",
        primary_provider="anthropic",
        specialist_model="allenai/scibert_scivocab_uncased",
        temperature=0.3,
        top_p=0.9,
        max_tokens=8192,
    ),
    tags=["research", "science", "methodology", "statistics"],
)


@VerticalRegistry.register(
    "research",
    config=RESEARCH_CONFIG,
    description="Research specialist for methodology and literature analysis",
)
class ResearchSpecialist(VerticalSpecialistAgent):
    """
    Research specialist agent.

    Provides expert guidance on:
    - Research methodology
    - Statistical analysis
    - Literature review
    - Scientific writing
    - Research ethics
    """

    # Research methodology patterns
    METHODOLOGY_PATTERNS = {
        "study_design": [
            r"randomized\s+controlled\s+trial|RCT",
            r"cohort\s+study",
            r"case.control\s+study",
            r"cross.sectional",
            r"meta.analysis",
            r"systematic\s+review",
        ],
        "statistical_methods": [
            r"t-test|t\s+test",
            r"ANOVA|analysis\s+of\s+variance",
            r"chi.square|χ²",
            r"regression",
            r"correlation",
            r"confidence\s+interval",
            r"p.value|p\s*<\s*0\.\d+",
        ],
        "sampling": [
            r"random\s+sampl",
            r"convenience\s+sample",
            r"stratified\s+sampl",
            r"sample\s+size",
            r"power\s+analysis",
        ],
        "bias_indicators": [
            r"selection\s+bias",
            r"confirmation\s+bias",
            r"publication\s+bias",
            r"recall\s+bias",
            r"attrition",
        ],
    }

    # Citation patterns
    CITATION_PATTERNS = {
        "apa": r"\([A-Z][a-z]+(?:\s+(?:et\s+al\.?|&\s+[A-Z][a-z]+))?,\s*\d{4}\)",
        "mla": r"[A-Z][a-z]+(?:\s+[a-z]+)*\s+\d+",
        "chicago": r"\d+\.\s+[A-Z][a-z]+",
        "doi": r"10\.\d{4,}/[^\s]+",
    }

    async def _execute_tool(
        self,
        tool: ToolConfig,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a research tool."""
        tool_name = tool.name

        if tool_name == "arxiv_search":
            return await self._arxiv_search(parameters)
        elif tool_name == "pubmed_search":
            return await self._pubmed_search(parameters)
        elif tool_name == "semantic_scholar":
            return await self._semantic_scholar_search(parameters)
        elif tool_name == "citation_check":
            return await self._citation_check(parameters)
        else:
            return {"error": f"Unknown tool: {tool_name}"}

    async def _arxiv_search(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Search arXiv for preprints."""
        query = parameters.get("query") or parameters.get("q") or ""
        limit = int(parameters.get("limit", 10))
        category = parameters.get("category")
        sort_by = parameters.get("sort_by", "relevance")
        sort_order = parameters.get("sort_order", "descending")
        return await arxiv_search(
            query,
            limit=limit,
            category=category,
            sort_by=sort_by,
            sort_order=sort_order,
        )

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

    async def _semantic_scholar_search(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Search Semantic Scholar."""
        query = parameters.get("query") or parameters.get("q") or ""
        limit = int(parameters.get("limit", 10))
        result = await semantic_scholar_search(query, limit=limit)
        if result.get("error"):
            fallback = await web_search_fallback(
                query,
                limit=limit,
                site="semanticscholar.org",
                note="Semantic Scholar connector unavailable; using web search fallback.",
            )
            return {
                "papers": fallback.get("results", []),
                "count": fallback.get("count", 0),
                "query": fallback.get("query", query),
                "mode": fallback.get("mode", "web_fallback"),
                "note": fallback.get("note"),
                "error": fallback.get("error"),
            }
        return {
            "papers": result.get("papers", []),
            "count": result.get("count", 0),
            "query": result.get("query", query),
            "mode": "connector",
        }

    async def _citation_check(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Check citations for validity and retractions."""
        citations = (
            parameters.get("citations")
            or parameters.get("references")
            or parameters.get("citation")
            or parameters.get("reference")
        )
        text_blob = parameters.get("text") or ""

        items: list[str] = []
        if citations:
            if isinstance(citations, str):
                items = [c.strip() for c in re.split(r"[\n;]+", citations) if c.strip()]
            elif isinstance(citations, list):
                items = [str(c).strip() for c in citations if str(c).strip()]
            else:
                items = [str(citations).strip()]

        if not items and text_blob:
            doi_pattern = r"10\\.\\d{4,9}/[-._;()/:A-Z0-9]+"
            items = re.findall(doi_pattern, text_blob, re.IGNORECASE)

        if not items:
            return {"citations": [], "retractions": [], "error": "citations or text required"}

        limit = int(parameters.get("limit", 5))
        evidence_limit = int(parameters.get("evidence_limit", 3))
        items = items[:limit]

        checked: list[dict[str, Any]] = []
        for citation in items:
            doi_match = re.search(r"10\\.\\d{4,9}/[-._;()/:A-Z0-9]+", citation, re.IGNORECASE)
            doi = doi_match.group(0) if doi_match else None
            result = await crossref_lookup(query=citation if not doi else None, doi=doi, limit=3)
            evidence = result.get("results", [])
            if not evidence:
                query = f"{citation} retraction"
                fallback = await web_search_fallback(
                    query,
                    limit=evidence_limit,
                    note="Crossref lookup unavailable; using web search fallback.",
                )
                checked.append(
                    {
                        "citation": citation,
                        "evidence": fallback.get("results", []),
                        "search_query": fallback.get("search_query", query),
                        "error": fallback.get("error"),
                        "mode": fallback.get("mode", "web_fallback"),
                    }
                )
                continue

            checked.append(
                {
                    "citation": citation,
                    "evidence": evidence,
                    "search_query": result.get("query", citation),
                    "error": result.get("error"),
                    "mode": "connector",
                }
            )

        return {
            "citations": checked,
            "retractions": [],
            "count": len(checked),
            "mode": "mixed",
            "note": "Crossref lookup is metadata-only; retraction detection is heuristic.",
        }

    async def _check_framework_compliance(
        self,
        content: str,
        framework: ComplianceConfig,
    ) -> list[dict[str, Any]]:
        """Check content against research compliance frameworks."""
        violations = []

        if framework.framework == "IRB":
            violations.extend(await self._check_irb_compliance(content, framework))
        elif framework.framework == "CONSORT":
            violations.extend(await self._check_consort_compliance(content, framework))
        elif framework.framework == "PRISMA":
            violations.extend(await self._check_prisma_compliance(content, framework))

        return violations

    async def _check_irb_compliance(
        self,
        content: str,
        framework: ComplianceConfig,
    ) -> list[dict[str, Any]]:
        """Check IRB/Ethics compliance."""
        violations = []
        content_lower = content.lower()

        # Check for human subjects research indicators
        has_human_subjects = any(
            term in content_lower
            for term in [
                "participant",
                "subject",
                "volunteer",
                "patient",
                "interview",
                "survey",
                "questionnaire",
                "blood sample",
                "tissue sample",
            ]
        )

        if has_human_subjects:
            # Informed consent check
            if "informed_consent" in framework.rules or not framework.rules:
                if not re.search(r"informed\s+consent|consent\s+form|consented", content_lower):
                    violations.append(
                        {
                            "framework": "IRB",
                            "rule": "Informed Consent",
                            "severity": "critical",
                            "message": "Human subjects research without informed consent documentation",
                        }
                    )

            # IRB approval check
            if not re.search(
                r"IRB|ethics\s+(?:committee|board)|institutional\s+review", content_lower
            ):
                violations.append(
                    {
                        "framework": "IRB",
                        "rule": "Ethics Approval",
                        "severity": "critical",
                        "message": "Human subjects research without IRB/ethics approval reference",
                    }
                )

            # Vulnerable populations check
            if "vulnerable_populations" in framework.rules or not framework.rules:
                vulnerable_terms = ["children", "minor", "pregnant", "prisoner", "cognitive impair"]
                if any(term in content_lower for term in vulnerable_terms):
                    if not re.search(
                        r"additional\s+protect|special\s+consider|guardian\s+consent", content_lower
                    ):
                        violations.append(
                            {
                                "framework": "IRB",
                                "rule": "Vulnerable Populations",
                                "severity": "high",
                                "message": "Vulnerable population without additional protections noted",
                            }
                        )

        return violations

    async def _check_consort_compliance(
        self,
        content: str,
        framework: ComplianceConfig,
    ) -> list[dict[str, Any]]:
        """Check CONSORT compliance for clinical trials."""
        violations = []
        content_lower = content.lower()

        # Check if this is a clinical trial
        is_trial = re.search(r"randomized|clinical\s+trial|RCT", content, re.IGNORECASE)

        if is_trial:
            # Randomization
            if "randomization" in framework.rules or not framework.rules:
                if not re.search(r"random(?:ization|ly|ised|ized)|allocation", content_lower):
                    violations.append(
                        {
                            "framework": "CONSORT",
                            "rule": "Randomization",
                            "severity": "high",
                            "message": "Clinical trial without randomization method described",
                        }
                    )

            # Sample size
            if "sample_size" in framework.rules or not framework.rules:
                if not re.search(
                    r"sample\s+size|power\s+(?:calculation|analysis)|n\s*=\s*\d+", content_lower
                ):
                    violations.append(
                        {
                            "framework": "CONSORT",
                            "rule": "Sample Size",
                            "severity": "medium",
                            "message": "Sample size justification not found",
                        }
                    )

            # Blinding
            if "blinding" in framework.rules or not framework.rules:
                if not re.search(
                    r"blind(?:ed|ing)|mask(?:ed|ing)|placebo|double.blind", content_lower
                ):
                    violations.append(
                        {
                            "framework": "CONSORT",
                            "rule": "Blinding",
                            "severity": "medium",
                            "message": "Blinding/masking not described",
                        }
                    )

        return violations

    async def _check_prisma_compliance(
        self,
        content: str,
        framework: ComplianceConfig,
    ) -> list[dict[str, Any]]:
        """Check PRISMA compliance for systematic reviews."""
        violations = []
        content_lower = content.lower()

        # Check if this is a systematic review
        is_review = re.search(r"systematic\s+review|meta.analysis", content, re.IGNORECASE)

        if is_review:
            # Search strategy
            if "search_strategy" in framework.rules or not framework.rules:
                if not re.search(
                    r"search\s+strateg|database|PubMed|Medline|Cochrane", content_lower
                ):
                    violations.append(
                        {
                            "framework": "PRISMA",
                            "rule": "Search Strategy",
                            "severity": "high",
                            "message": "Systematic review without search strategy described",
                        }
                    )

            # Selection criteria
            if "selection" in framework.rules or not framework.rules:
                if not re.search(
                    r"inclusion\s+criteria|exclusion\s+criteria|eligib", content_lower
                ):
                    violations.append(
                        {
                            "framework": "PRISMA",
                            "rule": "Selection Criteria",
                            "severity": "high",
                            "message": "Selection/eligibility criteria not specified",
                        }
                    )

            # Bias assessment
            if "bias_assessment" in framework.rules or not framework.rules:
                if not re.search(
                    r"risk\s+of\s+bias|quality\s+assessment|bias\s+assessment", content_lower
                ):
                    violations.append(
                        {
                            "framework": "PRISMA",
                            "rule": "Risk of Bias",
                            "severity": "medium",
                            "message": "Risk of bias assessment not described",
                        }
                    )

        return violations

    # _generate_response() inherited from base class - uses delegate LLM agent

    async def analyze_methodology(
        self,
        paper_text: str,
    ) -> dict[str, Any]:
        """
        Analyze research methodology.

        Args:
            paper_text: Research paper text

        Returns:
            Methodology analysis results
        """
        # Detect study design
        study_design = None
        for pattern in self.METHODOLOGY_PATTERNS.get("study_design", []):
            if re.search(pattern, paper_text, re.IGNORECASE):
                study_design = pattern
                break

        # Detect statistical methods
        stat_methods = []
        for pattern in self.METHODOLOGY_PATTERNS.get("statistical_methods", []):
            if re.search(pattern, paper_text, re.IGNORECASE):
                stat_methods.append(pattern)

        # Detect sampling approach
        sampling = []
        for pattern in self.METHODOLOGY_PATTERNS.get("sampling", []):
            if re.search(pattern, paper_text, re.IGNORECASE):
                sampling.append(pattern)

        # Check for bias indicators
        bias_risks = []
        for pattern in self.METHODOLOGY_PATTERNS.get("bias_indicators", []):
            if re.search(pattern, paper_text, re.IGNORECASE):
                bias_risks.append(pattern)

        # Check compliance
        compliance_violations = await self.check_compliance(paper_text)

        return {
            "study_design": study_design,
            "statistical_methods": stat_methods,
            "sampling_approach": sampling,
            "bias_risks": bias_risks,
            "compliance_violations": compliance_violations,
            "methodology_rating": self._rate_methodology(
                study_design, stat_methods, sampling, bias_risks
            ),
        }

    def _rate_methodology(
        self,
        study_design: str | None,
        stat_methods: list[str],
        sampling: list[str],
        bias_risks: list[str],
    ) -> str:
        """Rate overall methodology quality."""
        score = 0

        # Study design clarity
        if study_design:
            score += 2

        # Statistical rigor
        if len(stat_methods) >= 2:
            score += 2
        elif stat_methods:
            score += 1

        # Sampling description
        if sampling:
            score += 1

        # Bias awareness (mentioning bias is good)
        if bias_risks:
            score += 1

        if score >= 5:
            return "strong"
        elif score >= 3:
            return "adequate"
        else:
            return "needs_improvement"

    async def analyze_citations(
        self,
        paper_text: str,
    ) -> dict[str, Any]:
        """
        Analyze citation patterns in a paper.

        Args:
            paper_text: Research paper text

        Returns:
            Citation analysis results
        """
        citation_counts = {}

        for style, pattern in self.CITATION_PATTERNS.items():
            matches = re.findall(pattern, paper_text)
            citation_counts[style] = len(matches)

        # Find DOIs
        dois = re.findall(self.CITATION_PATTERNS["doi"], paper_text)

        # Estimate total citations
        total_citations = max(citation_counts.values()) if citation_counts else 0

        return {
            "citation_style_detected": (
                max(citation_counts, key=lambda k: citation_counts[k]) if citation_counts else None
            ),
            "estimated_citation_count": total_citations,
            "dois_found": len(dois),
            "citation_density": total_citations / max(len(paper_text.split()) / 1000, 1),
        }
