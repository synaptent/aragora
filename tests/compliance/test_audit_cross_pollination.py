"""Tests for compliance-audit cross-pollination.

Validates that:
1. ComplianceMonitor enriches status with audit findings context
2. AuditOrchestrator enriches results with compliance status context
3. Both cross-pollination paths are optional and gracefully degrade
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.compliance.monitor import (
    ComplianceHealth,
    ComplianceMonitor,
    ComplianceMonitorConfig,
    ComplianceStatus,
    FrameworkStatus,
    ViolationTrend,
)


# =========================================================================
# ComplianceMonitor -> Audit cross-pollination
# =========================================================================


class TestComplianceToAudit:
    """Test compliance monitor fetching audit context."""

    @pytest.fixture
    def monitor(self):
        """Create a ComplianceMonitor instance."""
        config = ComplianceMonitorConfig(enabled=False)
        return ComplianceMonitor(config)

    def test_fetch_audit_context_no_audit_module(self, monitor):
        """Returns None when audit module is not available."""
        with patch.dict("sys.modules", {"aragora.observability.audit_log": None}):
            status = ComplianceStatus()
            result = monitor._fetch_audit_context(status)
            # Should gracefully return None
            assert result is None

    def test_fetch_audit_context_no_log(self, monitor):
        """Returns None when audit log is not available."""
        with patch(
            "aragora.observability.audit_log.get_audit_log",
            return_value=None,
        ):
            status = ComplianceStatus(frameworks={"soc2": FrameworkStatus(framework="soc2")})
            result = monitor._fetch_audit_context(status)
            assert result is None

    def test_fetch_audit_context_no_frameworks(self, monitor):
        """Returns None when no compliance frameworks configured."""
        status = ComplianceStatus(frameworks={})
        result = monitor._fetch_audit_context(status)
        assert result is None

    def test_fetch_audit_context_with_findings(self, monitor):
        """Returns summary when audit findings match compliance frameworks."""
        status = ComplianceStatus(
            frameworks={
                "soc2": FrameworkStatus(framework="soc2", critical_violations=1),
            }
        )

        # Create mock AuditEvent objects with action/details attributes
        event1 = MagicMock()
        event1.action = "soc2_access_review"
        event1.details = {"severity": "critical", "framework": "soc2"}

        event2 = MagicMock()
        event2.action = "encryption_check"
        event2.details = {"severity": "major", "category": "soc2_encryption"}

        event3 = MagicMock()
        event3.action = "gdpr_consent_check"
        event3.details = {"severity": "minor", "category": "gdpr_consent"}

        mock_log = MagicMock()
        mock_log.query.return_value = [event1, event2, event3]

        with patch(
            "aragora.observability.audit_log.get_audit_log",
            return_value=mock_log,
        ):
            result = monitor._fetch_audit_context(status)
            assert result is not None
            assert result["relevant_findings"] == 2
            assert "critical" in result["severity_breakdown"]
            assert result["source"] == "audit_orchestrator"

    def test_fetch_audit_context_no_matching_findings(self, monitor):
        """Returns None when no findings match compliance frameworks."""
        status = ComplianceStatus(
            frameworks={
                "soc2": FrameworkStatus(framework="soc2"),
            }
        )

        event = MagicMock()
        event.action = "gdpr_consent_check"
        event.details = {"severity": "minor", "category": "gdpr_consent"}

        mock_log = MagicMock()
        mock_log.query.return_value = [event]

        with patch(
            "aragora.observability.audit_log.get_audit_log",
            return_value=mock_log,
        ):
            result = monitor._fetch_audit_context(status)
            assert result is None

    def test_fetch_audit_context_log_error(self, monitor):
        """Returns None gracefully on audit log errors."""
        status = ComplianceStatus(frameworks={"soc2": FrameworkStatus(framework="soc2")})

        mock_log = MagicMock()
        mock_log.query.side_effect = TypeError("query failed")

        with patch(
            "aragora.observability.audit_log.get_audit_log",
            return_value=mock_log,
        ):
            result = monitor._fetch_audit_context(status)
            assert result is None

    @pytest.mark.asyncio
    async def test_metadata_enriched_in_quick_check(self, monitor):
        """_run_quick_check enriches status metadata with audit context."""
        mock_context = {
            "relevant_findings": 3,
            "severity_breakdown": {"critical": 1, "major": 2},
            "frameworks_with_findings": ["soc2"],
            "source": "audit_orchestrator",
        }

        with (
            patch.object(monitor, "_fetch_audit_context", return_value=mock_context),
            patch.object(
                monitor, "_calculate_overall_health", return_value=ComplianceHealth.HEALTHY
            ),
            patch.object(monitor, "_calculate_overall_score", return_value=100.0),
            patch.object(monitor, "_calculate_trend", return_value=ViolationTrend.STABLE),
            patch.object(
                monitor,
                "_check_and_alert",
            ),
        ):
            status = await monitor._run_quick_check()
            assert "audit_findings_summary" in status.metadata
            assert status.metadata["audit_findings_summary"]["relevant_findings"] == 3


# =========================================================================
# AuditOrchestrator -> Compliance cross-pollination
# =========================================================================


class TestAuditToCompliance:
    """Test audit orchestrator fetching compliance context."""

    @pytest.fixture
    def orchestrator(self):
        """Create an AuditOrchestrator with default profile."""
        from aragora.audit.orchestrator import AuditOrchestrator, AuditVertical

        return AuditOrchestrator(verticals=[AuditVertical.SECURITY])

    def test_fetch_compliance_context_no_monitor(self, orchestrator):
        """Returns None when compliance monitor returns None."""
        with patch(
            "aragora.compliance.monitor.get_compliance_monitor",
            return_value=None,
        ):
            result = orchestrator._fetch_compliance_context()
            assert result is None

    def test_fetch_compliance_context_import_error(self, orchestrator):
        """Returns None when compliance module is not available."""
        # Directly test that ImportError is caught
        with patch.dict("sys.modules", {"aragora.compliance.monitor": None}):
            result = orchestrator._fetch_compliance_context()
            assert result is None

    def test_fetch_compliance_context_no_status(self, orchestrator):
        """Returns None when monitor has no status."""
        mock_monitor = MagicMock()
        mock_monitor._last_status = None

        with patch(
            "aragora.compliance.monitor.get_compliance_monitor",
            return_value=mock_monitor,
        ):
            result = orchestrator._fetch_compliance_context()
            assert result is None

    def test_fetch_compliance_context_with_status(self, orchestrator):
        """Returns compliance summary when status is available."""
        status = ComplianceStatus(
            overall_health=ComplianceHealth.DEGRADED,
            overall_score=85.0,
            open_violations=3,
            trend=ViolationTrend.WORSENING,
            frameworks={
                "soc2": FrameworkStatus(
                    framework="soc2",
                    score=80.0,
                    critical_violations=0,
                    major_violations=2,
                ),
            },
        )
        mock_monitor = MagicMock()
        mock_monitor._last_status = status

        with patch(
            "aragora.compliance.monitor.get_compliance_monitor",
            return_value=mock_monitor,
        ):
            result = orchestrator._fetch_compliance_context()
            assert result is not None
            assert result["overall_health"] == "degraded"
            assert result["overall_score"] == 85.0
            assert result["open_violations"] == 3
            assert result["trend"] == "worsening"
            assert "soc2" in result["frameworks"]
            assert result["frameworks"]["soc2"]["major"] == 2
            assert result["source"] == "compliance_monitor"

    @pytest.mark.asyncio
    async def test_compliance_context_in_run_result(self, orchestrator):
        """Compliance context appears in run() result metadata."""
        from aragora.audit.document_auditor import AuditSession

        mock_compliance = {
            "overall_health": "healthy",
            "overall_score": 100.0,
            "open_violations": 0,
            "trend": "stable",
            "frameworks": {},
            "source": "compliance_monitor",
        }

        with (
            patch.object(orchestrator, "_fetch_compliance_context", return_value=mock_compliance),
            patch.object(orchestrator, "_run_parallel", new_callable=AsyncMock),
            patch.object(orchestrator, "_run_serial", new_callable=AsyncMock),
        ):
            session = AuditSession(
                id="test-session",
                name="test.pdf",
                document_ids=["test.pdf"],
            )
            result = await orchestrator.run(chunks=[], session=session)
            assert "compliance_status" in result.metadata
            assert result.metadata["compliance_status"]["overall_health"] == "healthy"

    @pytest.mark.asyncio
    async def test_no_compliance_context_when_unavailable(self, orchestrator):
        """No metadata when compliance context is unavailable."""
        with (
            patch.object(orchestrator, "_fetch_compliance_context", return_value=None),
            patch.object(orchestrator, "_run_parallel", new_callable=AsyncMock),
            patch.object(orchestrator, "_run_serial", new_callable=AsyncMock),
        ):
            from aragora.audit.document_auditor import AuditSession

            session = AuditSession(
                id="test-session",
                name="test.pdf",
                document_ids=["test.pdf"],
            )
            result = await orchestrator.run(chunks=[], session=session)
            assert "compliance_status" not in result.metadata


# =========================================================================
# OrchestratorResult metadata field tests
# =========================================================================


class TestOrchestratorResultMetadata:
    """Test OrchestratorResult metadata field."""

    def test_metadata_in_to_dict(self):
        """Metadata appears in to_dict output when present."""
        from aragora.audit.orchestrator import OrchestratorResult

        result = OrchestratorResult(
            session_id="test",
            profile="test",
            verticals_run=[],
            findings=[],
            findings_by_vertical={},
            findings_by_severity={},
            total_chunks_processed=0,
            duration_ms=0.0,
            errors=[],
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            metadata={"compliance_status": {"overall_health": "healthy"}},
        )
        d = result.to_dict()
        assert "metadata" in d
        assert d["metadata"]["compliance_status"]["overall_health"] == "healthy"

    def test_metadata_not_in_to_dict_when_empty(self):
        """Metadata is omitted from to_dict when empty."""
        from aragora.audit.orchestrator import OrchestratorResult

        result = OrchestratorResult(
            session_id="test",
            profile="test",
            verticals_run=[],
            findings=[],
            findings_by_vertical={},
            findings_by_severity={},
            total_chunks_processed=0,
            duration_ms=0.0,
            errors=[],
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        d = result.to_dict()
        assert "metadata" not in d


# =========================================================================
# ComplianceStatus metadata field tests
# =========================================================================


class TestComplianceStatusMetadata:
    """Test ComplianceStatus metadata field."""

    def test_metadata_default_empty(self):
        """Metadata defaults to empty dict."""
        status = ComplianceStatus()
        assert status.metadata == {}

    def test_metadata_can_be_set(self):
        """Metadata can hold arbitrary data."""
        status = ComplianceStatus(metadata={"audit_findings_summary": {"count": 5}})
        assert status.metadata["audit_findings_summary"]["count"] == 5
