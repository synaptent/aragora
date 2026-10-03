"""
Academic document auditing for citation verification and plagiarism detection.

Detects:
- Citation formatting issues
- Missing or incomplete references
- Potential plagiarism indicators
- Academic integrity concerns
- Source quality issues
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any
from collections.abc import Sequence

from aragora.audit.base_auditor import (
    AuditContext,
    AuditorCapabilities,
    BaseAuditor,
    ChunkData,
)
from aragora.audit.document_auditor import (
    AuditFinding,
    FindingSeverity,
)

logger = logging.getLogger(__name__)


class CitationStyle(str, Enum):
    """Supported citation styles."""

    APA = "apa"
    MLA = "mla"
    CHICAGO = "chicago"
    HARVARD = "harvard"
    IEEE = "ieee"
    VANCOUVER = "vancouver"
    AMA = "ama"


@dataclass
class CitationPattern:
    """Pattern for detecting citations in a specific style."""

    style: CitationStyle
    in_text_pattern: re.Pattern[str]
    reference_pattern: re.Pattern[str]
    description: str


# Citation patterns by style
CITATION_PATTERNS = [
    CitationPattern(
        style=CitationStyle.APA,
        in_text_pattern=re.compile(
            r"\(([A-Z][a-z]+(?:\s*(?:&|and)\s*[A-Z][a-z]+)*),?\s*(\d{4})[a-z]?\)"
        ),
        reference_pattern=re.compile(
            r"^([A-Z][a-z]+,?\s*[A-Z]\.(?:\s*[A-Z]\.)*)(?:,?\s*(?:&|and)\s*[A-Z][a-z]+,?\s*[A-Z]\.)*\s*\((\d{4})\)"
        ),
        description="APA 7th Edition format",
    ),
    CitationPattern(
        style=CitationStyle.MLA,
        in_text_pattern=re.compile(r"\(([A-Z][a-z]+(?:\s+and\s+[A-Z][a-z]+)*)\s+(\d+)\)"),
        reference_pattern=re.compile(
            r"^([A-Z][a-z]+,\s*[A-Z][a-z]+)(?:,?\s*and\s*[A-Z][a-z]+,\s*[A-Z][a-z]+)*\."
        ),
        description="MLA 9th Edition format",
    ),
    CitationPattern(
        style=CitationStyle.IEEE,
        in_text_pattern=re.compile(r"\[(\d+)\]"),
        reference_pattern=re.compile(r"^\[(\d+)\]\s+[A-Z]\."),
        description="IEEE numbered citation format",
    ),
    CitationPattern(
        style=CitationStyle.CHICAGO,
        in_text_pattern=re.compile(r"\(([A-Z][a-z]+)\s+(\d{4}),\s*(\d+)\)"),
        reference_pattern=re.compile(r"^([A-Z][a-z]+,\s*[A-Z][a-z]+)\..*\d{4}\."),
        description="Chicago Author-Date format",
    ),
    CitationPattern(
        style=CitationStyle.HARVARD,
        in_text_pattern=re.compile(r"\(([A-Z][a-z]+(?:\s+and\s+[A-Z][a-z]+)*),?\s*(\d{4})\)"),
        reference_pattern=re.compile(r"^([A-Z][a-z]+,\s*[A-Z]\.(?:\s*[A-Z]\.)*)\s*\((\d{4})\)"),
        description="Harvard referencing format",
    ),
]


@dataclass
class ExtractedCitation:
    """An extracted citation from the document."""

    text: str
    style: CitationStyle | None
    author: str
    year: str | None
    position: int
    is_in_text: bool
    is_reference: bool
    confidence: float


@dataclass
class PlagiarismIndicator:
    """An indicator of potential plagiarism."""

    name: str
    pattern: re.Pattern[str]
    severity: FindingSeverity
    description: str
    recommendation: str


# Plagiarism indicators
PLAGIARISM_INDICATORS = [
    PlagiarismIndicator(
        name="Inconsistent Writing Style",
        pattern=re.compile(r"(?i)(suddenly|notably|interestingly|it is important to note)"),
        severity=FindingSeverity.LOW,
        description="Transitional phrase that may indicate copied content",
        recommendation="Verify original authorship and proper citation",
    ),
    PlagiarismIndicator(
        name="Direct Quote Without Citation",
        pattern=re.compile(r'"[^"]{50,}"(?!\s*\([^)]+\d{4}[^)]*\))'),
        severity=FindingSeverity.HIGH,
        description="Long quoted text without apparent citation",
        recommendation="Add proper citation for quoted material",
    ),
    PlagiarismIndicator(
        name="Wikipedia Reference",
        pattern=re.compile(r"(?i)wikipedia"),
        severity=FindingSeverity.MEDIUM,
        description="Wikipedia cited as source (generally not acceptable in academic work)",
        recommendation="Replace with primary or peer-reviewed sources",
    ),
    PlagiarismIndicator(
        name="Broken Citation",
        pattern=re.compile(r"\([^)]*\d{4}[^)]*\?\?[^)]*\)"),
        severity=FindingSeverity.MEDIUM,
        description="Citation appears incomplete or broken",
        recommendation="Fix incomplete citation",
    ),
    PlagiarismIndicator(
        name="Et Al Misuse",
        pattern=re.compile(r"(?i)et\s+al(?!\.|\s+\d{4})"),
        severity=FindingSeverity.LOW,
        description="'Et al.' used without year or improper formatting",
        recommendation="Format 'et al.' citations properly",
    ),
]


class AcademicAuditor(BaseAuditor):
    """
    Audits academic documents for citation quality and plagiarism indicators.

    Provides citation extraction, format verification, and plagiarism detection.
    """

    @property
    def audit_type_id(self) -> str:
        return "academic"

    @property
    def display_name(self) -> str:
        return "Academic Integrity"

    @property
    def description(self) -> str:
        return "Detects citation issues, plagiarism indicators, and academic integrity concerns"

    @property
    def capabilities(self) -> AuditorCapabilities:
        return AuditorCapabilities(
            supports_chunk_analysis=True,
            supports_cross_document=True,
            requires_llm=True,
            finding_categories=[
                "citation_format",
                "missing_citation",
                "plagiarism_indicator",
                "source_quality",
                "reference_mismatch",
            ],
            supported_document_types=[
                "research_paper",
                "thesis",
                "dissertation",
                "journal_article",
                "conference_paper",
                "essay",
            ],
        )

    def __init__(
        self,
        citation_style: CitationStyle | None = None,
        check_plagiarism: bool = True,
    ):
        """
        Initialize academic auditor.

        Args:
            citation_style: Expected citation style (auto-detected if None)
            check_plagiarism: Whether to check for plagiarism indicators
        """
        self._expected_style = citation_style
        self._check_plagiarism = check_plagiarism
        self._detected_style: CitationStyle | None = None
        self._in_text_citations: list[ExtractedCitation] = []
        self._references: list[ExtractedCitation] = []

    async def analyze_chunk(
        self,
        chunk: ChunkData,
        context: AuditContext,
    ) -> list[AuditFinding]:
        """Analyze a chunk for academic integrity issues."""
        findings = []

        # Extract citations
        citations = self._extract_citations(chunk)
        self._in_text_citations.extend([c for c in citations if c.is_in_text])
        self._references.extend([c for c in citations if c.is_reference])

        # Check citation formatting
        format_findings = self._check_citation_format(chunk, citations, context)
        findings.extend(format_findings)

        # Check for plagiarism indicators
        if self._check_plagiarism:
            plagiarism_findings = self._check_plagiarism_indicators(chunk, context)
            findings.extend(plagiarism_findings)

        # LLM-based analysis for complex issues
        if len(chunk.content) > 200:
            llm_findings = await self._llm_academic_analysis(chunk, context)
            findings.extend(llm_findings)

        return findings

    def _extract_citations(self, chunk: ChunkData) -> list[ExtractedCitation]:
        """Extract all citations from a chunk."""
        citations = []
        content = chunk.content

        for pattern_def in CITATION_PATTERNS:
            # Check in-text citations
            for match in pattern_def.in_text_pattern.finditer(content):
                lastindex = match.lastindex or 0
                author = match.group(1) if lastindex >= 1 else ""
                year = match.group(2) if lastindex >= 2 else None

                citation = ExtractedCitation(
                    text=match.group(0),
                    style=pattern_def.style,
                    author=author,
                    year=year,
                    position=match.start(),
                    is_in_text=True,
                    is_reference=False,
                    confidence=0.85,
                )
                citations.append(citation)

            # Check reference entries (line by line)
            for line in content.split("\n"):
                reference_match = pattern_def.reference_pattern.match(line.strip())
                if reference_match:
                    lastindex = reference_match.lastindex or 0
                    author = reference_match.group(1) if lastindex >= 1 else ""
                    year = reference_match.group(2) if lastindex >= 2 else None

                    citation = ExtractedCitation(
                        text=line.strip()[:200],
                        style=pattern_def.style,
                        author=author,
                        year=year,
                        position=content.find(line),
                        is_in_text=False,
                        is_reference=True,
                        confidence=0.8,
                    )
                    citations.append(citation)

        return citations

    def _check_citation_format(
        self,
        chunk: ChunkData,
        citations: list[ExtractedCitation],
        context: AuditContext,
    ) -> list[AuditFinding]:
        """Check citation formatting consistency."""
        findings: list[AuditFinding] = []

        if not citations:
            return findings

        # Detect dominant style
        style_counts: dict[CitationStyle, int] = {}
        for citation in citations:
            if citation.style:
                style_counts[citation.style] = style_counts.get(citation.style, 0) + 1

        if style_counts:
            dominant_style = max(style_counts, key=lambda k: style_counts[k])
            self._detected_style = dominant_style

            # Check for inconsistent styles
            if len(style_counts) > 1:
                inconsistent_styles = [s.value for s in style_counts if s != dominant_style]
                finding = context.create_finding(
                    document_id=chunk.document_id,
                    chunk_id=chunk.id,
                    title="Inconsistent Citation Styles",
                    description=f"Multiple citation styles detected. Dominant: {dominant_style.value}, Others: {', '.join(inconsistent_styles)}",
                    severity=FindingSeverity.MEDIUM,
                    category="citation_format",
                    confidence=0.9,
                    recommendation=f"Use consistent {dominant_style.value.upper()} formatting throughout",
                    tags=["citation", "formatting"],
                )
                findings.append(finding)

            # Check if detected style matches expected
            if self._expected_style and dominant_style != self._expected_style:
                finding = context.create_finding(
                    document_id=chunk.document_id,
                    chunk_id=chunk.id,
                    title="Wrong Citation Style",
                    description=f"Expected {self._expected_style.value.upper()}, found {dominant_style.value.upper()}",
                    severity=FindingSeverity.HIGH,
                    category="citation_format",
                    confidence=0.85,
                    recommendation=f"Convert all citations to {self._expected_style.value.upper()} format",
                    tags=["citation", "style_mismatch"],
                )
                findings.append(finding)

        return findings

    def _check_plagiarism_indicators(
        self,
        chunk: ChunkData,
        context: AuditContext,
    ) -> list[AuditFinding]:
        """Check for plagiarism indicators."""
        findings = []

        for indicator in PLAGIARISM_INDICATORS:
            matches = list(indicator.pattern.finditer(chunk.content))
            if matches:
                # Only report first match to avoid flooding
                match = matches[0]
                start = max(0, match.start() - 50)
                end = min(len(chunk.content), match.end() + 50)
                evidence = chunk.content[start:end]

                finding = context.create_finding(
                    document_id=chunk.document_id,
                    chunk_id=chunk.id,
                    title=f"Plagiarism Indicator: {indicator.name}",
                    description=indicator.description,
                    severity=indicator.severity,
                    category="plagiarism_indicator",
                    confidence=0.7,
                    evidence_text=evidence,
                    evidence_location=f"Position {match.start()}",
                    recommendation=indicator.recommendation,
                    tags=["plagiarism", "academic_integrity"],
                )
                findings.append(finding)

        return findings

    async def _llm_academic_analysis(
        self,
        chunk: ChunkData,
        context: AuditContext,
    ) -> list[AuditFinding]:
        """Use LLM for deeper academic analysis."""
        findings = []

        try:
            from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

            agent = AnthropicAPIAgent(name="academic_reviewer", model=context.model)

            prompt = f"""Analyze this academic text for integrity issues:

{chunk.content[:8000]}

Check for:
1. Claims without citations (assertions that need sources)
2. Paraphrasing that's too close to original (if apparent)
3. Citation quality (are sources likely peer-reviewed?)
4. Logical flow and argument structure
5. Technical accuracy concerns

Report issues as JSON array:
[{{"title": "...", "severity": "high|medium|low", "category": "missing_citation|source_quality|paraphrasing_concern|accuracy_issue", "evidence": "...", "recommendation": "..."}}]

If no issues, respond with: []"""

            response = await agent.generate(prompt)

            # Parse response
            import json

            json_match = re.search(r"\[[\s\S]*\]", response)
            if json_match:
                try:
                    items = json.loads(json_match.group())
                    for item in items:
                        finding = context.create_finding(
                            document_id=chunk.document_id,
                            chunk_id=chunk.id,
                            title=item.get("title", "Academic Issue"),
                            description="",
                            severity=FindingSeverity(item.get("severity", "medium").lower()),
                            category=item.get("category", "source_quality"),
                            confidence=0.7,
                            evidence_text=item.get("evidence", ""),
                            recommendation=item.get("recommendation", ""),
                            tags=["academic", "llm_detected"],
                        )
                        findings.append(finding)
                except json.JSONDecodeError as e:
                    logger.debug("Failed to parse JSON data: %s", e)

        except (ImportError, AttributeError, ValueError, OSError, RuntimeError) as e:
            logger.debug("Academic LLM analysis skipped: %s", e)

        return findings

    async def cross_document_analysis(
        self,
        chunks: Sequence[ChunkData],
        context: AuditContext,
    ) -> list[AuditFinding]:
        """Analyze citation coverage across the document."""
        findings = []

        # Check for citation-reference mismatches
        in_text_authors = {c.author.lower() for c in self._in_text_citations if c.author}
        reference_authors = {c.author.split(",")[0].lower() for c in self._references if c.author}

        # Citations without references
        missing_refs = in_text_authors - reference_authors
        if missing_refs:
            finding = context.create_finding(
                document_id=chunks[0].document_id if chunks else "unknown",
                title="Citations Without References",
                description=f"In-text citations found without corresponding reference entries: {', '.join(list(missing_refs)[:5])}{'...' if len(missing_refs) > 5 else ''}",
                severity=FindingSeverity.HIGH,
                category="reference_mismatch",
                confidence=0.8,
                recommendation="Add reference entries for all in-text citations",
                affected_scope="document",
                tags=["citation", "reference"],
            )
            findings.append(finding)

        # Unused references
        unused_refs = reference_authors - in_text_authors
        if unused_refs:
            finding = context.create_finding(
                document_id=chunks[0].document_id if chunks else "unknown",
                title="Unused References",
                description=f"Reference entries without corresponding in-text citations: {', '.join(list(unused_refs)[:5])}{'...' if len(unused_refs) > 5 else ''}",
                severity=FindingSeverity.LOW,
                category="reference_mismatch",
                confidence=0.75,
                recommendation="Remove unused references or add in-text citations",
                affected_scope="document",
                tags=["citation", "reference"],
            )
            findings.append(finding)

        # Citation density check
        total_content_length = sum(len(c.content) for c in chunks)
        citation_count = len(self._in_text_citations)
        if total_content_length > 5000 and citation_count < 5:
            finding = context.create_finding(
                document_id=chunks[0].document_id if chunks else "unknown",
                title="Low Citation Density",
                description=f"Document has only {citation_count} citations for {total_content_length} characters of text",
                severity=FindingSeverity.MEDIUM,
                category="missing_citation",
                confidence=0.6,
                recommendation="Add more citations to support claims and arguments",
                affected_scope="document",
                tags=["citation", "density"],
            )
            findings.append(finding)

        return findings

    async def post_audit_hook(
        self,
        findings: list[AuditFinding],
        context: AuditContext,
    ) -> list[AuditFinding]:
        """Post-process findings and reset state."""
        # Reset state
        self._in_text_citations = []
        self._references = []
        self._detected_style = None

        return findings


class CitationExtractor:
    """
    Standalone citation extractor for quick analysis.

    Can be used independently of the full audit system.
    """

    def __init__(self, style: CitationStyle | None = None):
        self._style = style

    def extract(self, text: str) -> list[dict[str, Any]]:
        """
        Extract all citations from text.

        Returns:
            List of citation dictionaries
        """
        results = []

        patterns = CITATION_PATTERNS
        if self._style:
            patterns = [p for p in patterns if p.style == self._style]

        for pattern_def in patterns:
            for match in pattern_def.in_text_pattern.finditer(text):
                lastindex = match.lastindex or 0
                results.append(
                    {
                        "type": "in_text",
                        "style": pattern_def.style.value,
                        "text": match.group(0),
                        "author": match.group(1) if lastindex >= 1 else None,
                        "year": match.group(2) if lastindex >= 2 else None,
                        "position": match.start(),
                    }
                )

        return results

    def get_bibliography(self, text: str) -> list[dict[str, Any]]:
        """
        Extract bibliography/references section.

        Returns:
            List of reference entries
        """
        results = []

        # Look for references section
        ref_section_pattern = re.compile(
            r"(?i)(references|bibliography|works\s+cited|literature\s+cited)\s*\n",
            re.MULTILINE,
        )

        match = ref_section_pattern.search(text)
        if match:
            # Extract text after references header
            ref_text = text[match.end() :]

            # Split into individual references
            for line in ref_text.split("\n"):
                line = line.strip()
                if line and len(line) > 20:
                    results.append(
                        {
                            "text": line[:500],
                            "type": "reference",
                        }
                    )

        return results


__all__ = [
    "AcademicAuditor",
    "CitationExtractor",
    "CitationStyle",
    "CITATION_PATTERNS",
    "PLAGIARISM_INDICATORS",
]
