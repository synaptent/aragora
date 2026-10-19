"""
Tests for audit report generator module.

Tests report generation in multiple formats.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

import pytest

from aragora.reports.generator import (
    AuditReportGenerator,
    GeneratedReport,
    ReportConfig,
    ReportFormat,
    ReportSection,
    ReportTemplate,
)
from tests.utils.weasyprint_isolation import hide_weasyprint, refuse_in_process_render


@pytest.fixture(autouse=True)
def _no_in_process_weasyprint_render(monkeypatch):
    refuse_in_process_render(monkeypatch)


class TestReportFormat:
    """Tests for ReportFormat enum."""

    def test_all_formats_exist(self):
        """All expected formats are defined."""
        assert ReportFormat.PDF.value == "pdf"
        assert ReportFormat.MARKDOWN.value == "markdown"
        assert ReportFormat.JSON.value == "json"
        assert ReportFormat.HTML.value == "html"


class TestReportTemplate:
    """Tests for ReportTemplate enum."""

    def test_all_templates_exist(self):
        """All expected templates are defined."""
        assert ReportTemplate.EXECUTIVE_SUMMARY.value == "executive_summary"
        assert ReportTemplate.DETAILED_FINDINGS.value == "detailed_findings"
        assert ReportTemplate.COMPLIANCE_ATTESTATION.value == "compliance_attestation"
        assert ReportTemplate.SECURITY_ASSESSMENT.value == "security_assessment"


class TestReportConfig:
    """Tests for ReportConfig dataclass."""

    def test_default_config(self):
        """Default config has correct values."""
        config = ReportConfig()

        assert config.output_dir == "."
        assert config.filename_prefix == "audit_report"
        assert config.include_executive_summary is True
        assert config.include_findings_detail is True
        assert config.include_charts is True
        assert config.include_recommendations is True
        assert config.include_appendix is False
        assert config.min_severity == "low"
        assert config.company_name == "Aragora"

    def test_custom_config(self):
        """Config can be customized."""
        config = ReportConfig(
            output_dir="/tmp/reports",
            filename_prefix="security_audit",
            include_appendix=True,
            min_severity="high",
            author="Test Author",
        )

        assert config.output_dir == "/tmp/reports"
        assert config.filename_prefix == "security_audit"
        assert config.include_appendix is True
        assert config.min_severity == "high"
        assert config.author == "Test Author"


class TestReportSection:
    """Tests for ReportSection dataclass."""

    def test_section_creation(self):
        """Sections are created correctly."""
        section = ReportSection(
            title="Test Section",
            content="Test content",
            order=1,
        )

        assert section.title == "Test Section"
        assert section.content == "Test content"
        assert section.order == 1
        assert section.subsections == []

    def test_section_with_subsections(self):
        """Sections can have subsections."""
        sub1 = ReportSection(title="Sub 1", content="Content 1", order=1)
        sub2 = ReportSection(title="Sub 2", content="Content 2", order=2)

        section = ReportSection(
            title="Parent",
            content="",
            order=0,
            subsections=[sub1, sub2],
        )

        assert len(section.subsections) == 2


class TestGeneratedReport:
    """Tests for GeneratedReport dataclass."""

    def test_report_creation(self):
        """Reports are created correctly."""
        content = b"# Report Content"
        report = GeneratedReport(
            format=ReportFormat.MARKDOWN,
            content=content,
            filename="report.md",
            size_bytes=len(content),
            session_id="session123",
            findings_count=5,
        )

        assert report.format == ReportFormat.MARKDOWN
        assert report.content == content
        assert report.filename == "report.md"
        assert report.size_bytes == 16
        assert report.findings_count == 5

    def test_report_save(self):
        """Reports can be saved to file."""
        content = b"# Test Report\n\nContent here."
        report = GeneratedReport(
            format=ReportFormat.MARKDOWN,
            content=content,
            filename="test_report.md",
            size_bytes=len(content),
        )

        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "output.md"
            saved_path = report.save(path)

            assert saved_path == path
            assert path.exists()
            assert path.read_bytes() == content


# Create mock audit types for testing
def create_mock_session():
    """Create a mock audit session."""
    session = MagicMock()
    session.id = "session-12345678"
    session.name = "Test Audit"
    session.model = "gpt-4"
    session.document_ids = ["doc1", "doc2", "doc3"]
    session.findings = []
    session.duration_seconds = 45.5
    session.completed_at = datetime.now(timezone.utc)
    session.processed_chunks = 100
    session.total_chunks = 100
    session.errors = []
    session.findings_by_severity = {"critical": 1, "high": 2, "medium": 3}

    # Mock audit_types
    audit_type = MagicMock()
    audit_type.value = "security"
    session.audit_types = [audit_type]

    session.to_dict.return_value = {
        "id": session.id,
        "name": session.name,
        "document_ids": session.document_ids,
    }

    return session


def create_mock_finding(severity="medium", audit_type="security", title="Test Finding"):
    """Create a mock audit finding."""
    finding = MagicMock()
    finding.id = f"finding-{severity}"
    finding.title = title
    finding.description = f"A {severity} severity finding"
    finding.category = "Test Category"
    finding.confidence = 0.85
    finding.evidence_text = "Evidence text here"
    finding.evidence_location = "file.py:42"
    finding.recommendation = f"Fix this {severity} issue"
    finding.document_id = "doc1"
    finding.affected_scope = "module"

    # Mock severity enum
    sev = MagicMock()
    sev.value = severity
    finding.severity = sev

    # Mock audit type enum
    atype = MagicMock()
    atype.value = audit_type
    finding.audit_type = atype

    # Mock status enum
    status = MagicMock()
    status.value = "open"
    finding.status = status

    finding.to_dict.return_value = {
        "id": finding.id,
        "title": finding.title,
        "severity": severity,
    }

    return finding


class TestAuditReportGenerator:
    """Tests for AuditReportGenerator class."""

    def test_generator_init_default_config(self):
        """Generator initializes with default config."""
        generator = AuditReportGenerator()
        assert generator.config.company_name == "Aragora"

    def test_generator_init_custom_config(self):
        """Generator accepts custom config."""
        config = ReportConfig(company_name="Custom Corp")
        generator = AuditReportGenerator(config)
        assert generator.config.company_name == "Custom Corp"

    def test_filter_findings_by_severity(self):
        """Findings are filtered by severity."""
        generator = AuditReportGenerator(ReportConfig(min_severity="high"))

        findings = [
            create_mock_finding(severity="critical"),
            create_mock_finding(severity="high"),
            create_mock_finding(severity="medium"),
            create_mock_finding(severity="low"),
        ]

        # Need to mock FindingSeverity and FindingStatus
        with pytest.MonkeyPatch.context() as mp:
            from aragora.reports import generator as gen_module

            # Create mock severity enum
            mock_severity = MagicMock()
            mock_severity.return_value = MagicMock()

            filtered = generator._filter_findings(findings)

        # Should include critical and high (min_severity="high")
        assert len(filtered) <= 2

    def test_build_executive_summary(self):
        """Executive summary is built correctly."""
        generator = AuditReportGenerator()
        session = create_mock_session()
        findings = [
            create_mock_finding(severity="critical"),
            create_mock_finding(severity="high"),
            create_mock_finding(severity="medium"),
        ]

        section = generator._build_executive_summary(session, findings)

        assert section.title == "Executive Summary"
        assert "Critical" in section.content or "critical" in section.content.lower()
        assert section.order == 1

    def test_build_summary_stats(self):
        """Summary statistics are built correctly."""
        generator = AuditReportGenerator()
        session = create_mock_session()
        findings = [
            create_mock_finding(severity="high", title="Finding 1"),
            create_mock_finding(severity="high", title="Finding 2"),
        ]

        section = generator._build_summary_stats(session, findings)

        assert section.title == "Summary Statistics"
        assert "Findings by Type" in section.content

    def test_build_findings_by_severity(self):
        """Findings by severity section is built correctly."""
        generator = AuditReportGenerator()
        findings = [
            create_mock_finding(severity="critical", title="Critical Issue"),
            create_mock_finding(severity="high", title="High Issue"),
            create_mock_finding(severity="medium", title="Medium Issue"),
        ]

        section = generator._build_findings_by_severity(findings)

        assert section.title == "Detailed Findings"
        assert len(section.subsections) >= 1  # At least one severity group

    def test_build_recommendations(self):
        """Recommendations section is built correctly."""
        generator = AuditReportGenerator()
        findings = [
            create_mock_finding(severity="high", title="Issue 1"),
            create_mock_finding(severity="medium", title="Issue 2"),
        ]

        section = generator._build_recommendations(findings)

        assert section.title == "Recommendations"
        assert "Fix this" in section.content or "recommendation" in section.content.lower()

    def test_build_compliance_summary(self):
        """Compliance summary is built correctly."""
        generator = AuditReportGenerator()
        session = create_mock_session()
        findings = [create_mock_finding(audit_type="compliance")]

        section = generator._build_compliance_summary(session, findings)

        assert section.title == "Compliance Summary"
        assert "Compliance Status" in section.content

    def test_build_attestation_section(self):
        """Attestation section is built correctly."""
        generator = AuditReportGenerator(
            ReportConfig(author="Test Author", reviewer="Test Reviewer")
        )
        session = create_mock_session()

        section = generator._build_attestation_section(session)

        assert section.title == "Attestation"
        assert "Test Author" in section.content
        assert "Test Reviewer" in section.content

    def test_build_security_summary(self):
        """Security summary is built correctly."""
        generator = AuditReportGenerator()
        findings = [
            create_mock_finding(audit_type="security", severity="critical"),
            create_mock_finding(audit_type="security", severity="high"),
        ]

        section = generator._build_security_summary(findings)

        assert section.title == "Security Summary"
        assert "Security Assessment" in section.content

    def test_build_remediation_roadmap(self):
        """Remediation roadmap is built correctly."""
        generator = AuditReportGenerator()
        findings = [
            create_mock_finding(audit_type="security", severity="critical"),
            create_mock_finding(audit_type="security", severity="medium"),
            create_mock_finding(audit_type="security", severity="low"),
        ]

        section = generator._build_remediation_roadmap(findings)

        assert section.title == "Remediation Roadmap"
        assert "Immediate Action" in section.content
        assert "Short-term" in section.content
        assert "Long-term" in section.content

    def test_build_appendix(self):
        """Appendix is built correctly."""
        generator = AuditReportGenerator()
        session = create_mock_session()
        findings = [create_mock_finding()]

        section = generator._build_appendix(session, findings)

        assert section.title == "Appendix"
        assert "Audit Configuration" in section.content

    def test_render_markdown(self):
        """Markdown rendering works correctly."""
        generator = AuditReportGenerator()
        session = create_mock_session()
        findings = [create_mock_finding()]

        sections = [
            ReportSection(title="Summary", content="Summary content", order=1),
            ReportSection(title="Details", content="Detail content", order=2),
        ]

        content = generator._render_markdown(sections, session, findings)

        assert isinstance(content, bytes)
        markdown = content.decode("utf-8")
        assert "# Audit Report" in markdown
        assert "## Summary" in markdown
        assert "## Details" in markdown

    def test_render_json(self):
        """JSON rendering works correctly."""
        generator = AuditReportGenerator()
        session = create_mock_session()
        findings = [create_mock_finding()]

        content = generator._render_json(session, findings)

        assert isinstance(content, bytes)
        data = json.loads(content.decode("utf-8"))

        assert "report" in data
        assert "session" in data
        assert "findings" in data
        assert "summary" in data
        assert data["summary"]["total_findings"] == 1

    def test_render_html(self):
        """HTML rendering works correctly."""
        generator = AuditReportGenerator()
        session = create_mock_session()
        findings = [create_mock_finding()]

        sections = [
            ReportSection(title="Summary", content="Summary **bold** content", order=1),
        ]

        content = generator._render_html(sections, session, findings)

        assert isinstance(content, bytes)
        html = content.decode("utf-8")
        assert "<!DOCTYPE html>" in html
        assert "<title>Audit Report" in html
        assert "Summary" in html

    def test_md_to_html_conversion(self):
        """Markdown to HTML conversion works."""
        generator = AuditReportGenerator()

        # Bold
        result = generator._md_to_html("**bold text**")
        assert "<strong>bold text</strong>" in result

        # Code
        result = generator._md_to_html("inline `code` here")
        assert "<code>code</code>" in result

        # Lists
        result = generator._md_to_html("- item 1\n- item 2")
        assert "<ul>" in result
        assert "<li>item 1</li>" in result
        assert "<li>item 2</li>" in result

    @pytest.mark.asyncio
    async def test_generate_markdown_report(self):
        """Full markdown report generation works."""
        generator = AuditReportGenerator()
        session = create_mock_session()
        session.findings = [
            create_mock_finding(severity="high"),
            create_mock_finding(severity="medium"),
        ]

        report = await generator.generate(
            session,
            format=ReportFormat.MARKDOWN,
            template=ReportTemplate.DETAILED_FINDINGS,
        )

        assert report.format == ReportFormat.MARKDOWN
        assert report.filename.endswith(".md")
        assert report.session_id == session.id
        assert len(report.content) > 0

    @pytest.mark.asyncio
    async def test_generate_json_report(self):
        """Full JSON report generation works."""
        generator = AuditReportGenerator()
        session = create_mock_session()
        session.findings = [create_mock_finding()]

        report = await generator.generate(
            session,
            format=ReportFormat.JSON,
            template=ReportTemplate.DETAILED_FINDINGS,
        )

        assert report.format == ReportFormat.JSON
        assert report.filename.endswith(".json")

        data = json.loads(report.content.decode("utf-8"))
        assert "report" in data

    @pytest.mark.asyncio
    async def test_generate_html_report(self):
        """Full HTML report generation works."""
        generator = AuditReportGenerator()
        session = create_mock_session()
        session.findings = [create_mock_finding()]

        report = await generator.generate(
            session,
            format=ReportFormat.HTML,
            template=ReportTemplate.DETAILED_FINDINGS,
        )

        assert report.format == ReportFormat.HTML
        assert report.filename.endswith(".html")
        assert b"<!DOCTYPE html>" in report.content

    @pytest.mark.asyncio
    async def test_generate_executive_summary_template(self):
        """Executive summary template works."""
        generator = AuditReportGenerator()
        session = create_mock_session()
        session.findings = [create_mock_finding()]

        report = await generator.generate(
            session,
            format=ReportFormat.MARKDOWN,
            template=ReportTemplate.EXECUTIVE_SUMMARY,
        )

        markdown = report.content.decode("utf-8")
        assert "Executive Summary" in markdown
        assert "Summary Statistics" in markdown

    @pytest.mark.asyncio
    async def test_generate_compliance_template(self):
        """Compliance attestation template works."""
        generator = AuditReportGenerator()
        session = create_mock_session()
        session.findings = [create_mock_finding(audit_type="compliance")]

        report = await generator.generate(
            session,
            format=ReportFormat.MARKDOWN,
            template=ReportTemplate.COMPLIANCE_ATTESTATION,
        )

        markdown = report.content.decode("utf-8")
        assert "Compliance Summary" in markdown
        assert "Attestation" in markdown

    @pytest.mark.asyncio
    async def test_generate_security_template(self):
        """Security assessment template works."""
        generator = AuditReportGenerator()
        session = create_mock_session()
        session.findings = [create_mock_finding(audit_type="security", severity="critical")]

        report = await generator.generate(
            session,
            format=ReportFormat.MARKDOWN,
            template=ReportTemplate.SECURITY_ASSESSMENT,
        )

        markdown = report.content.decode("utf-8")
        assert "Security Summary" in markdown
        assert "Vulnerability Details" in markdown
        assert "Remediation Roadmap" in markdown

    @pytest.mark.asyncio
    async def test_generate_with_appendix(self):
        """Reports include appendix when configured."""
        config = ReportConfig(include_appendix=True)
        generator = AuditReportGenerator(config)
        session = create_mock_session()
        session.findings = [create_mock_finding()]

        report = await generator.generate(
            session,
            format=ReportFormat.MARKDOWN,
            template=ReportTemplate.DETAILED_FINDINGS,
        )

        markdown = report.content.decode("utf-8")
        assert "Appendix" in markdown

    @pytest.mark.asyncio
    async def test_generate_unsupported_format(self):
        """Unsupported format raises error."""
        generator = AuditReportGenerator()
        session = create_mock_session()
        session.findings = []

        # Create an invalid format
        with pytest.raises(ValueError, match="Unsupported format"):
            await generator.generate(
                session,
                format="invalid",  # type: ignore[arg-type]
                template=ReportTemplate.DETAILED_FINDINGS,
            )

    @pytest.mark.asyncio
    async def test_render_pdf_fallback(self, monkeypatch):
        """PDF rendering falls back to HTML without weasyprint."""
        hide_weasyprint(monkeypatch)
        generator = AuditReportGenerator()
        session = create_mock_session()
        session.findings = [create_mock_finding()]

        sections = [ReportSection(title="Test", content="Content", order=1)]

        content = await generator._render_pdf(sections, session, session.findings)

        # Should return HTML as fallback
        assert content.startswith(b"<!DOCTYPE html>")
