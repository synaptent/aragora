"""Tests for Harness Result Adapter.

Covers:
- AdapterConfig configuration options
- HarnessResultAdapter adapt() method
- adapt_batch() for multiple results
- merge_duplicate_findings() deduplication
- Convenience functions adapt_to_audit_findings() and adapt_multiple_results()
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aragora.harnesses.base import AnalysisFinding, AnalysisType, HarnessResult


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_finding():
    """Create a sample AnalysisFinding."""
    return AnalysisFinding(
        id="finding-001",
        title="SQL Injection Vulnerability",
        description="User input not sanitized before SQL query",
        severity="high",
        confidence=0.9,
        category="security",
        file_path="src/db.py",
        line_start=42,
        line_end=45,
        code_snippet="query = f'SELECT * FROM users WHERE id={user_id}'",
        recommendation="Use parameterized queries",
    )


@pytest.fixture
def sample_harness_result(sample_finding):
    """Create a sample HarnessResult."""
    return HarnessResult(
        harness="claude-code",
        analysis_type=AnalysisType.SECURITY,
        success=True,
        findings=[sample_finding],
        files_analyzed=10,
        lines_analyzed=500,
    )


@pytest.fixture
def multiple_findings():
    """Create multiple findings for batch testing."""
    return [
        AnalysisFinding(
            id="1",
            title="Issue One",
            description="First issue",
            severity="critical",
            confidence=0.95,
            category="security",
            file_path="src/auth.py",
            line_start=10,
            line_end=15,
        ),
        AnalysisFinding(
            id="2",
            title="Issue Two",
            description="Second issue",
            severity="medium",
            confidence=0.7,
            category="quality",
            file_path="src/utils.py",
            line_start=20,
        ),
        AnalysisFinding(
            id="3",
            title="Issue Three",
            description="Third issue",
            severity="low",
            confidence=0.6,
            category="documentation",
            file_path="src/models.py",
        ),
    ]


# =============================================================================
# AdapterConfig Tests
# =============================================================================


class TestAdapterConfig:
    """Tests for AdapterConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        from aragora.harnesses.adapter import AdapterConfig

        config = AdapterConfig()

        assert config.min_confidence == 0.5
        assert config.id_prefix == "harness"

    def test_default_severity_mapping(self):
        """Test default severity mappings."""
        from aragora.harnesses.adapter import AdapterConfig

        config = AdapterConfig()

        assert config.severity_mapping["critical"] == "critical"
        assert config.severity_mapping["high"] == "high"
        assert config.severity_mapping["medium"] == "medium"
        assert config.severity_mapping["low"] == "low"
        assert config.severity_mapping["info"] == "info"
        assert config.severity_mapping["informational"] == "info"
        assert config.severity_mapping["warning"] == "medium"
        assert config.severity_mapping["error"] == "high"

    def test_default_type_mapping(self):
        """Test default analysis type mappings."""
        from aragora.harnesses.adapter import AdapterConfig

        config = AdapterConfig()

        assert config.type_mapping[AnalysisType.SECURITY.value] == "security"
        assert config.type_mapping[AnalysisType.QUALITY.value] == "quality"
        assert config.type_mapping[AnalysisType.ARCHITECTURE.value] == "consistency"
        assert config.type_mapping[AnalysisType.PERFORMANCE.value] == "quality"

    def test_default_confidence_adjustments(self):
        """Test default confidence adjustments per harness."""
        from aragora.harnesses.adapter import AdapterConfig

        config = AdapterConfig()

        assert config.confidence_adjustments["claude-code"] == 0.0
        assert config.confidence_adjustments["codex"] == -0.05
        assert config.confidence_adjustments["default"] == 0.0

    def test_custom_config(self):
        """Test custom configuration."""
        from aragora.harnesses.adapter import AdapterConfig

        config = AdapterConfig(
            min_confidence=0.7,
            id_prefix="custom",
            severity_mapping={"custom": "high"},
        )

        assert config.min_confidence == 0.7
        assert config.id_prefix == "custom"
        assert config.severity_mapping["custom"] == "high"


# =============================================================================
# HarnessResultAdapter Tests
# =============================================================================


class TestHarnessResultAdapter:
    """Tests for HarnessResultAdapter class."""

    def test_adapter_initialization(self):
        """Test adapter initialization with default config."""
        from aragora.harnesses.adapter import HarnessResultAdapter

        adapter = HarnessResultAdapter()

        assert adapter.config is not None
        assert adapter.config.min_confidence == 0.5

    def test_adapter_custom_config(self):
        """Test adapter initialization with custom config."""
        from aragora.harnesses.adapter import AdapterConfig, HarnessResultAdapter

        config = AdapterConfig(min_confidence=0.8)
        adapter = HarnessResultAdapter(config)

        assert adapter.config.min_confidence == 0.8


class TestHarnessResultAdapterAdapt:
    """Tests for the adapt() method."""

    def test_adapt_single_finding(self, sample_harness_result):
        """Test adapting a result with a single finding."""
        from aragora.harnesses.adapter import HarnessResultAdapter

        adapter = HarnessResultAdapter()
        findings = adapter.adapt(sample_harness_result)

        assert len(findings) == 1

        finding = findings[0]
        assert finding.title == "SQL Injection Vulnerability"
        assert finding.severity.value == "high"
        assert finding.confidence == 0.9
        assert finding.document_id == "src/db.py"
        assert finding.found_by == "claude-code"

    def test_adapt_preserves_severity(self, sample_harness_result):
        """Test that severity is correctly mapped."""
        from aragora.harnesses.adapter import HarnessResultAdapter

        adapter = HarnessResultAdapter()
        findings = adapter.adapt(sample_harness_result)

        assert findings[0].severity.value == "high"

    def test_adapt_evidence_location_with_lines(self, sample_finding):
        """Test evidence location includes line numbers."""
        from aragora.harnesses.adapter import HarnessResultAdapter

        result = HarnessResult(
            harness="codex",
            analysis_type=AnalysisType.SECURITY,
            success=True,
            findings=[sample_finding],
        )

        adapter = HarnessResultAdapter()
        findings = adapter.adapt(result)

        # Line 42-45 should be in evidence location
        assert "42" in findings[0].evidence_location
        assert "45" in findings[0].evidence_location

    def test_adapt_evidence_location_single_line(self):
        """Test evidence location with single line number."""
        from aragora.harnesses.adapter import HarnessResultAdapter

        finding = AnalysisFinding(
            id="f1",
            title="Test",
            description="Desc",
            severity="medium",
            confidence=0.8,
            category="quality",
            file_path="test.py",
            line_start=10,
            line_end=10,  # Same line
        )

        result = HarnessResult(
            harness="claude-code",
            analysis_type=AnalysisType.QUALITY,
            success=True,
            findings=[finding],
        )

        adapter = HarnessResultAdapter()
        findings = adapter.adapt(result)

        # Should have file:line format, not file:line-line
        assert findings[0].evidence_location == "test.py:10"

    def test_adapt_confidence_adjustment_codex(self):
        """Test confidence adjustment for Codex harness."""
        from aragora.harnesses.adapter import HarnessResultAdapter

        finding = AnalysisFinding(
            id="f1",
            title="Test",
            description="Desc",
            severity="medium",
            confidence=0.8,
            category="quality",
            file_path="test.py",
        )

        result = HarnessResult(
            harness="codex",
            analysis_type=AnalysisType.QUALITY,
            success=True,
            findings=[finding],
        )

        adapter = HarnessResultAdapter()
        findings = adapter.adapt(result)

        # Codex has -0.05 adjustment
        assert findings[0].confidence == 0.75

    def test_adapt_respects_min_confidence(self):
        """Test that min_confidence is respected."""
        from aragora.harnesses.adapter import AdapterConfig, HarnessResultAdapter

        finding = AnalysisFinding(
            id="f1",
            title="Test",
            description="Desc",
            severity="medium",
            confidence=0.3,  # Below default min
            category="quality",
            file_path="test.py",
        )

        result = HarnessResult(
            harness="claude-code",
            analysis_type=AnalysisType.QUALITY,
            success=True,
            findings=[finding],
        )

        config = AdapterConfig(min_confidence=0.5)
        adapter = HarnessResultAdapter(config)
        findings = adapter.adapt(result)

        # Should be clamped to min_confidence
        assert findings[0].confidence == 0.5

    def test_adapt_generates_unique_ids(self, sample_harness_result):
        """Test that adapted findings have unique IDs."""
        from aragora.harnesses.adapter import HarnessResultAdapter

        adapter = HarnessResultAdapter()
        findings = adapter.adapt(sample_harness_result)

        assert findings[0].id.startswith("harness_")
        assert "claude-code" in findings[0].id
        assert "finding-001" in findings[0].id

    def test_adapt_maps_audit_type(self, sample_harness_result):
        """Test that analysis type is mapped to audit type."""
        from aragora.harnesses.adapter import HarnessResultAdapter

        adapter = HarnessResultAdapter()
        findings = adapter.adapt(sample_harness_result)

        # SECURITY analysis should map to security audit type
        assert findings[0].audit_type.value == "security"

    def test_adapt_empty_result(self):
        """Test adapting a result with no findings."""
        from aragora.harnesses.adapter import HarnessResultAdapter

        result = HarnessResult(
            harness="claude-code",
            analysis_type=AnalysisType.GENERAL,
            success=True,
            findings=[],
        )

        adapter = HarnessResultAdapter()
        findings = adapter.adapt(result)

        assert findings == []

    def test_adapt_unknown_severity(self):
        """Test handling of unknown severity values."""
        from aragora.harnesses.adapter import HarnessResultAdapter

        finding = AnalysisFinding(
            id="f1",
            title="Test",
            description="Desc",
            severity="unknown_severity",
            confidence=0.8,
            category="quality",
            file_path="test.py",
        )

        result = HarnessResult(
            harness="claude-code",
            analysis_type=AnalysisType.QUALITY,
            success=True,
            findings=[finding],
        )

        adapter = HarnessResultAdapter()
        findings = adapter.adapt(result)

        # Should default to medium
        assert findings[0].severity.value == "medium"

    def test_adapt_uses_description_as_evidence_fallback(self):
        """Test that description is used as evidence when no code snippet."""
        from aragora.harnesses.adapter import HarnessResultAdapter

        finding = AnalysisFinding(
            id="f1",
            title="Test",
            description="This is the description that should become evidence",
            severity="medium",
            confidence=0.8,
            category="quality",
            file_path="test.py",
            code_snippet="",  # Empty snippet
        )

        result = HarnessResult(
            harness="claude-code",
            analysis_type=AnalysisType.QUALITY,
            success=True,
            findings=[finding],
        )

        adapter = HarnessResultAdapter()
        findings = adapter.adapt(result)

        assert "description that should become evidence" in findings[0].evidence_text


class TestHarnessResultAdapterBatch:
    """Tests for batch adaptation."""

    def test_adapt_batch_multiple_results(self, multiple_findings):
        """Test adapting multiple harness results."""
        from aragora.harnesses.adapter import HarnessResultAdapter

        result1 = HarnessResult(
            harness="claude-code",
            analysis_type=AnalysisType.SECURITY,
            success=True,
            findings=multiple_findings[:2],
        )

        result2 = HarnessResult(
            harness="codex",
            analysis_type=AnalysisType.QUALITY,
            success=True,
            findings=[multiple_findings[2]],
        )

        adapter = HarnessResultAdapter()
        findings = adapter.adapt_batch([result1, result2])

        assert len(findings) == 3

    def test_adapt_batch_empty_list(self):
        """Test adapting empty results list."""
        from aragora.harnesses.adapter import HarnessResultAdapter

        adapter = HarnessResultAdapter()
        findings = adapter.adapt_batch([])

        assert findings == []


class TestMergeDuplicateFindings:
    """Tests for duplicate finding detection and merging."""

    def test_merge_exact_duplicates(self):
        """Test merging findings with same location."""
        from aragora.harnesses.adapter import HarnessResultAdapter

        finding1 = AnalysisFinding(
            id="f1",
            title="SQL Injection in database query",
            description="Issue in query",
            severity="high",
            confidence=0.8,
            category="security",
            file_path="db.py",
            line_start=10,
        )

        finding2 = AnalysisFinding(
            id="f2",
            title="SQL Injection in database query handler",  # Similar title
            description="Same issue different harness",
            severity="high",
            confidence=0.9,  # Higher confidence
            category="security",
            file_path="db.py",
            line_start=10,  # Same location
        )

        result1 = HarnessResult(
            harness="claude-code",
            analysis_type=AnalysisType.SECURITY,
            success=True,
            findings=[finding1],
        )

        result2 = HarnessResult(
            harness="codex",
            analysis_type=AnalysisType.SECURITY,
            success=True,
            findings=[finding2],
        )

        adapter = HarnessResultAdapter()
        findings = adapter.adapt_batch([result1, result2])
        merged = adapter.merge_duplicate_findings(findings)

        # Should merge to one finding with higher confidence
        assert len(merged) == 1
        assert merged[0].confidence >= 0.85  # Should have higher confidence

    def test_merge_keeps_different_files(self):
        """Test that findings in different files are not merged."""
        from aragora.harnesses.adapter import HarnessResultAdapter

        finding1 = AnalysisFinding(
            id="f1",
            title="Issue",
            description="Issue desc",
            severity="medium",
            confidence=0.8,
            category="quality",
            file_path="file1.py",
            line_start=10,
        )

        finding2 = AnalysisFinding(
            id="f2",
            title="Issue",  # Same title
            description="Issue desc",
            severity="medium",
            confidence=0.8,
            category="quality",
            file_path="file2.py",  # Different file
            line_start=10,
        )

        result = HarnessResult(
            harness="claude-code",
            analysis_type=AnalysisType.QUALITY,
            success=True,
            findings=[finding1, finding2],
        )

        adapter = HarnessResultAdapter()
        findings = adapter.adapt(result)
        merged = adapter.merge_duplicate_findings(findings)

        # Should keep both (different files)
        assert len(merged) == 2

    def test_merge_different_titles_same_location(self):
        """Test that different titles at same location are not merged."""
        from aragora.harnesses.adapter import HarnessResultAdapter

        # These findings have the same location but DIFFERENT line numbers
        # which creates different evidence_location keys
        finding1 = AnalysisFinding(
            id="f1",
            title="Security Issue",
            description="Desc",
            severity="high",
            confidence=0.8,
            category="security",
            file_path="file.py",
            line_start=10,
        )

        finding2 = AnalysisFinding(
            id="f2",
            title="Completely Different Quality Issue",  # Very different title
            description="Desc",
            severity="medium",
            confidence=0.7,
            category="quality",
            file_path="file.py",
            line_start=20,  # Different line, different key
        )

        result = HarnessResult(
            harness="claude-code",
            analysis_type=AnalysisType.GENERAL,
            success=True,
            findings=[finding1, finding2],
        )

        adapter = HarnessResultAdapter()
        findings = adapter.adapt(result)
        merged = adapter.merge_duplicate_findings(findings)

        # Different locations should not be merged
        assert len(merged) == 2


# =============================================================================
# Convenience Functions Tests
# =============================================================================


class TestAdaptToAuditFindings:
    """Tests for adapt_to_audit_findings convenience function."""

    def test_basic_usage(self, sample_harness_result):
        """Test basic convenience function usage."""
        from aragora.harnesses.adapter import adapt_to_audit_findings

        findings = adapt_to_audit_findings(sample_harness_result)

        assert len(findings) == 1
        assert findings[0].title == "SQL Injection Vulnerability"

    def test_with_custom_config(self, sample_harness_result):
        """Test convenience function with custom config."""
        from aragora.harnesses.adapter import AdapterConfig, adapt_to_audit_findings

        config = AdapterConfig(id_prefix="custom")
        findings = adapt_to_audit_findings(sample_harness_result, config)

        assert findings[0].id.startswith("custom_")


class TestAdaptMultipleResults:
    """Tests for adapt_multiple_results convenience function."""

    def test_basic_usage(self, multiple_findings):
        """Test basic multiple results adaptation."""
        from aragora.harnesses.adapter import adapt_multiple_results

        result1 = HarnessResult(
            harness="claude-code",
            analysis_type=AnalysisType.SECURITY,
            success=True,
            findings=[multiple_findings[0]],
        )

        result2 = HarnessResult(
            harness="codex",
            analysis_type=AnalysisType.QUALITY,
            success=True,
            findings=[multiple_findings[1]],
        )

        findings = adapt_multiple_results([result1, result2])

        assert len(findings) == 2

    def test_with_merge_disabled(self, multiple_findings):
        """Test multiple results without duplicate merging."""
        from aragora.harnesses.adapter import adapt_multiple_results

        # Create duplicate findings
        finding1 = AnalysisFinding(
            id="f1",
            title="Same Issue",
            description="Desc",
            severity="high",
            confidence=0.8,
            category="security",
            file_path="file.py",
            line_start=10,
        )

        finding2 = AnalysisFinding(
            id="f2",
            title="Same Issue",  # Same title
            description="Desc",
            severity="high",
            confidence=0.9,
            category="security",
            file_path="file.py",
            line_start=10,  # Same location
        )

        result1 = HarnessResult(
            harness="claude-code",
            analysis_type=AnalysisType.SECURITY,
            success=True,
            findings=[finding1],
        )

        result2 = HarnessResult(
            harness="codex",
            analysis_type=AnalysisType.SECURITY,
            success=True,
            findings=[finding2],
        )

        # With merge disabled, should keep both
        findings = adapt_multiple_results([result1, result2], merge_duplicates=False)
        assert len(findings) == 2

        # With merge enabled (default), should merge
        findings_merged = adapt_multiple_results([result1, result2], merge_duplicates=True)
        assert len(findings_merged) == 1


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestAdapterEdgeCases:
    """Test edge cases and error handling."""

    def test_adapt_finding_with_no_lines(self):
        """Test adapting finding without line numbers."""
        from aragora.harnesses.adapter import HarnessResultAdapter

        finding = AnalysisFinding(
            id="f1",
            title="Test",
            description="Desc",
            severity="medium",
            confidence=0.8,
            category="quality",
            file_path="test.py",
            # No line_start or line_end
        )

        result = HarnessResult(
            harness="claude-code",
            analysis_type=AnalysisType.QUALITY,
            success=True,
            findings=[finding],
        )

        adapter = HarnessResultAdapter()
        findings = adapter.adapt(result)

        # Evidence location should just be the file path
        assert findings[0].evidence_location == "test.py"

    def test_adapt_finding_with_invalid_confidence(self):
        """Test confidence is clamped to valid range."""
        from aragora.harnesses.adapter import HarnessResultAdapter

        finding = AnalysisFinding(
            id="f1",
            title="Test",
            description="Desc",
            severity="medium",
            confidence=1.5,  # Invalid - over 1.0
            category="quality",
            file_path="test.py",
        )

        result = HarnessResult(
            harness="claude-code",
            analysis_type=AnalysisType.QUALITY,
            success=True,
            findings=[finding],
        )

        adapter = HarnessResultAdapter()
        findings = adapter.adapt(result)

        # Should be clamped to 1.0
        assert findings[0].confidence == 1.0

    def test_adapt_handles_recommendation(self, sample_harness_result):
        """Test that recommendation is preserved."""
        from aragora.harnesses.adapter import HarnessResultAdapter

        adapter = HarnessResultAdapter()
        findings = adapter.adapt(sample_harness_result)

        assert findings[0].recommendation == "Use parameterized queries"

    def test_unknown_harness_uses_default_adjustment(self):
        """Test unknown harness uses default confidence adjustment."""
        from aragora.harnesses.adapter import HarnessResultAdapter

        finding = AnalysisFinding(
            id="f1",
            title="Test",
            description="Desc",
            severity="medium",
            confidence=0.8,
            category="quality",
            file_path="test.py",
        )

        result = HarnessResult(
            harness="unknown-harness",  # Not in adjustment map
            analysis_type=AnalysisType.QUALITY,
            success=True,
            findings=[finding],
        )

        adapter = HarnessResultAdapter()
        findings = adapter.adapt(result)

        # Default adjustment is 0.0, so confidence unchanged
        assert findings[0].confidence == 0.8


# =============================================================================
# Integration Tests
# =============================================================================


class TestAdapterIntegration:
    """Integration tests for the adapter system."""

    def test_full_workflow(self):
        """Test complete adaptation workflow."""
        from aragora.harnesses.adapter import AdapterConfig, adapt_multiple_results

        # Create findings from multiple harnesses
        security_finding = AnalysisFinding(
            id="sec-001",
            title="Hardcoded Password",
            description="Password is hardcoded in source",
            severity="critical",
            confidence=0.95,
            category="security",
            file_path="config.py",
            line_start=15,
            line_end=15,
            code_snippet="password = 'secret123'",
            recommendation="Use environment variables",
        )

        quality_finding = AnalysisFinding(
            id="qual-001",
            title="Complex Function",
            description="Function has high cyclomatic complexity",
            severity="medium",
            confidence=0.75,
            category="quality",
            file_path="utils.py",
            line_start=50,
            line_end=100,
        )

        claude_result = HarnessResult(
            harness="claude-code",
            analysis_type=AnalysisType.SECURITY,
            success=True,
            findings=[security_finding],
        )

        codex_result = HarnessResult(
            harness="codex",
            analysis_type=AnalysisType.QUALITY,
            success=True,
            findings=[quality_finding],
        )

        # Adapt with custom config
        config = AdapterConfig(min_confidence=0.6)
        findings = adapt_multiple_results(
            [claude_result, codex_result],
            merge_duplicates=True,
            config=config,
        )

        assert len(findings) == 2

        # Verify security finding
        sec = next(f for f in findings if "sec-001" in f.id)
        assert sec.severity.value == "critical"
        assert sec.audit_type.value == "security"
        assert sec.confidence == 0.95

        # Verify quality finding (codex has -0.05 adjustment)
        qual = next(f for f in findings if "qual-001" in f.id)
        assert qual.severity.value == "medium"
        assert qual.confidence == 0.70  # 0.75 - 0.05
