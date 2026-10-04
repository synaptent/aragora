"""
Tests for Gauntlet API resource.

Tests cover:
- GauntletAPI.run() and run_async() for starting analysis
- GauntletAPI.get_receipt() and get_receipt_async() for retrieving results
- GauntletAPI.run_and_wait() for synchronous execution
- GauntletAPI.get() and get_async() for status
- GauntletAPI.delete() and delete_async() for cleanup
- GauntletAPI.list_personas() and list_personas_async()
- GauntletAPI.list_results() and list_results_async()
- GauntletAPI.get_heatmap() and get_heatmap_async()
- GauntletAPI.compare() and compare_async()
- Model validation for all Gauntlet models
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.client.client import AragoraClient
from aragora.client.errors import AragoraAPIError
from aragora.client.models import (
    Finding,
    GauntletComparison,
    GauntletHeatmapExtended,
    GauntletPersona,
    GauntletPersonaCategory,
    GauntletReceipt,
    GauntletResult,
    GauntletResultStatus,
    GauntletRun,
    GauntletRunRequest,
    GauntletRunResponse,
    GauntletRunStatus,
    GauntletVerdict,
)
from aragora.client.resources.gauntlet import GauntletAPI


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_client() -> AragoraClient:
    """Create a mock AragoraClient."""
    client = MagicMock(spec=AragoraClient)
    return client


@pytest.fixture
def gauntlet_api(mock_client: AragoraClient) -> GauntletAPI:
    """Create a GauntletAPI with mock client."""
    return GauntletAPI(mock_client)


@pytest.fixture
def sample_timestamp() -> str:
    """Sample ISO timestamp for tests."""
    return datetime.now(timezone.utc).isoformat()


# ============================================================================
# GauntletVerdict Tests
# ============================================================================


class TestGauntletVerdict:
    """Tests for GauntletVerdict enum."""

    def test_approved_value(self):
        """Test APPROVED verdict value."""
        assert GauntletVerdict.APPROVED.value == "approved"

    def test_approved_with_conditions_value(self):
        """Test APPROVED_WITH_CONDITIONS verdict value."""
        assert GauntletVerdict.APPROVED_WITH_CONDITIONS.value == "approved_with_conditions"

    def test_needs_review_value(self):
        """Test NEEDS_REVIEW verdict value."""
        assert GauntletVerdict.NEEDS_REVIEW.value == "needs_review"

    def test_rejected_value(self):
        """Test REJECTED verdict value."""
        assert GauntletVerdict.REJECTED.value == "rejected"


# ============================================================================
# Finding Model Tests
# ============================================================================


class TestFindingModel:
    """Tests for Finding model."""

    def test_finding_defaults(self):
        """Test Finding default values."""
        finding = Finding()
        assert finding.severity == "medium"
        assert finding.category == "general"
        assert finding.title is None
        assert finding.description is None

    def test_finding_with_values(self):
        """Test Finding with custom values."""
        finding = Finding(
            severity="high",
            category="security",
            title="SQL Injection",
            description="User input not sanitized",
            location="api.py:42",
            mitigation="Use parameterized queries",
        )
        assert finding.severity == "high"
        assert finding.category == "security"
        assert finding.title == "SQL Injection"
        assert finding.location == "api.py:42"

    def test_finding_title_from_description(self):
        """Test Finding auto-fills title from description."""
        finding = Finding(description="Something is wrong")
        assert finding.title == "Something is wrong"

    def test_finding_description_from_title(self):
        """Test Finding auto-fills description from title."""
        finding = Finding(title="Issue detected")
        assert finding.description == "Issue detected"

    def test_finding_mitigation_from_suggestion(self):
        """Test Finding auto-fills mitigation from suggestion."""
        finding = Finding(suggestion="Fix the code")
        assert finding.mitigation == "Fix the code"


# ============================================================================
# GauntletReceipt Model Tests
# ============================================================================


class TestGauntletReceiptModel:
    """Tests for GauntletReceipt model."""

    def test_receipt_minimal(self):
        """Test GauntletReceipt with minimal data."""
        receipt = GauntletReceipt()
        assert receipt.findings == []
        assert receipt.verdict is None

    def test_receipt_with_verdict(self):
        """Test GauntletReceipt with verdict."""
        receipt = GauntletReceipt(
            receipt_id="rcpt-123",
            gauntlet_id="gnt-456",
            verdict=GauntletVerdict.APPROVED,
            risk_score=0.2,
        )
        assert receipt.receipt_id == "rcpt-123"
        assert receipt.verdict == GauntletVerdict.APPROVED
        assert receipt.risk_score == 0.2

    def test_receipt_score_sync(self):
        """Test GauntletReceipt syncs risk_score and score."""
        receipt = GauntletReceipt(score=0.5)
        assert receipt.risk_score == 0.5
        assert receipt.score == 0.5

    def test_receipt_risk_score_sync(self):
        """Test GauntletReceipt syncs score from risk_score."""
        receipt = GauntletReceipt(risk_score=0.3)
        assert receipt.risk_score == 0.3
        assert receipt.score == 0.3

    def test_receipt_findings_list(self):
        """Test GauntletReceipt with findings list."""
        receipt = GauntletReceipt(
            findings=[
                Finding(severity="high", title="Issue 1"),
                Finding(severity="low", title="Issue 2"),
            ]
        )
        assert len(receipt.findings) == 2
        assert receipt.findings[0].severity == "high"

    def test_receipt_findings_from_strings(self):
        """Test GauntletReceipt coerces string findings."""
        receipt = GauntletReceipt(findings=["Finding A", "Finding B"])
        assert len(receipt.findings) == 2
        assert receipt.findings[0].title == "Finding A"
        assert receipt.findings[0].severity == "low"

    def test_receipt_findings_none_becomes_empty(self):
        """Test GauntletReceipt handles None findings."""
        receipt = GauntletReceipt(findings=None)
        assert receipt.findings == []


# ============================================================================
# GauntletRunRequest/Response Model Tests
# ============================================================================


class TestGauntletRunRequestModel:
    """Tests for GauntletRunRequest model."""

    def test_request_minimal(self):
        """Test GauntletRunRequest with required fields only."""
        request = GauntletRunRequest(input_content="Test content")
        assert request.input_content == "Test content"
        assert request.input_type == "text"
        assert request.persona == "security"
        assert request.profile == "default"

    def test_request_custom_values(self):
        """Test GauntletRunRequest with custom values."""
        request = GauntletRunRequest(
            input_content="Policy document",
            input_type="policy",
            persona="gdpr",
            profile="thorough",
        )
        assert request.input_type == "policy"
        assert request.persona == "gdpr"
        assert request.profile == "thorough"


class TestGauntletRunResponseModel:
    """Tests for GauntletRunResponse model."""

    def test_response_required_fields(self):
        """Test GauntletRunResponse with required fields."""
        response = GauntletRunResponse(
            gauntlet_id="gnt-123",
            status="pending",
        )
        assert response.gauntlet_id == "gnt-123"
        assert response.status == "pending"
        assert response.estimated_duration is None

    def test_response_with_duration(self):
        """Test GauntletRunResponse with estimated duration."""
        response = GauntletRunResponse(
            gauntlet_id="gnt-123",
            status="running",
            estimated_duration=60,
        )
        assert response.estimated_duration == 60


# ============================================================================
# GauntletRun Model Tests
# ============================================================================


class TestGauntletRunModel:
    """Tests for GauntletRun model."""

    def test_run_minimal(self):
        """Test GauntletRun with minimal data."""
        run = GauntletRun(id="gnt-123")
        assert run.id == "gnt-123"
        assert run.status == GauntletRunStatus.PENDING
        assert run.config == {}
        assert run.progress == {}

    def test_run_with_status(self):
        """Test GauntletRun with status."""
        run = GauntletRun(
            id="gnt-123",
            name="Security Audit",
            status=GauntletRunStatus.RUNNING,
            progress={"completed": 50, "total": 100},
        )
        assert run.name == "Security Audit"
        assert run.status == GauntletRunStatus.RUNNING
        assert run.progress["completed"] == 50


class TestGauntletRunStatus:
    """Tests for GauntletRunStatus enum."""

    def test_all_status_values(self):
        """Test all status values exist."""
        assert GauntletRunStatus.PENDING.value == "pending"
        assert GauntletRunStatus.RUNNING.value == "running"
        assert GauntletRunStatus.COMPLETED.value == "completed"
        assert GauntletRunStatus.FAILED.value == "failed"
        assert GauntletRunStatus.CANCELLED.value == "cancelled"


# ============================================================================
# GauntletPersona Model Tests
# ============================================================================


class TestGauntletPersonaModel:
    """Tests for GauntletPersona model."""

    def test_persona_required_fields(self):
        """Test GauntletPersona with required fields."""
        persona = GauntletPersona(id="p-sec", name="Security Tester")
        assert persona.id == "p-sec"
        assert persona.name == "Security Tester"
        assert persona.description == ""
        assert persona.enabled is True

    def test_persona_full(self):
        """Test GauntletPersona with all fields."""
        persona = GauntletPersona(
            id="p-adv",
            name="Adversary",
            description="Simulates malicious actor",
            category=GauntletPersonaCategory.ADVERSARIAL,
            severity="high",
            tags=["security", "attack"],
            example_prompts=["Bypass auth", "Exfiltrate data"],
            enabled=True,
        )
        assert persona.category == GauntletPersonaCategory.ADVERSARIAL
        assert persona.severity == "high"
        assert "security" in persona.tags
        assert len(persona.example_prompts) == 2


class TestGauntletPersonaCategory:
    """Tests for GauntletPersonaCategory enum."""

    def test_all_categories(self):
        """Test all category values."""
        assert GauntletPersonaCategory.ADVERSARIAL.value == "adversarial"
        assert GauntletPersonaCategory.EDGE_CASE.value == "edge_case"
        assert GauntletPersonaCategory.STRESS.value == "stress"
        assert GauntletPersonaCategory.COMPLIANCE.value == "compliance"
        assert GauntletPersonaCategory.CUSTOM.value == "custom"


# ============================================================================
# GauntletResult Model Tests
# ============================================================================


class TestGauntletResultModel:
    """Tests for GauntletResult model."""

    def test_result_minimal(self):
        """Test GauntletResult with required fields."""
        result = GauntletResult(id="res-123", gauntlet_id="gnt-456")
        assert result.id == "res-123"
        assert result.gauntlet_id == "gnt-456"
        assert result.status == GauntletResultStatus.PASS
        assert result.confidence == 0.0

    def test_result_full(self):
        """Test GauntletResult with all fields."""
        result = GauntletResult(
            id="res-123",
            gauntlet_id="gnt-456",
            scenario="SQL Injection Test",
            persona="security",
            status=GauntletResultStatus.FAIL,
            verdict="Vulnerable",
            confidence=0.95,
            risk_level="critical",
            duration_ms=1500,
            findings=[{"severity": "critical", "description": "SQL injection found"}],
        )
        assert result.status == GauntletResultStatus.FAIL
        assert result.risk_level == "critical"
        assert len(result.findings) == 1


class TestGauntletResultStatus:
    """Tests for GauntletResultStatus enum."""

    def test_all_statuses(self):
        """Test all result status values."""
        assert GauntletResultStatus.PASS.value == "pass"
        assert GauntletResultStatus.FAIL.value == "fail"
        assert GauntletResultStatus.ERROR.value == "error"
        assert GauntletResultStatus.SKIP.value == "skip"


# ============================================================================
# GauntletHeatmapExtended Model Tests
# ============================================================================


class TestGauntletHeatmapExtendedModel:
    """Tests for GauntletHeatmapExtended model."""

    def test_heatmap_minimal(self):
        """Test GauntletHeatmapExtended with required fields."""
        heatmap = GauntletHeatmapExtended(gauntlet_id="gnt-123")
        assert heatmap.gauntlet_id == "gnt-123"
        assert heatmap.dimensions == {}
        assert heatmap.matrix == []
        assert heatmap.overall_risk == 0.0

    def test_heatmap_full(self):
        """Test GauntletHeatmapExtended with data."""
        heatmap = GauntletHeatmapExtended(
            gauntlet_id="gnt-123",
            dimensions={"x": ["sql", "xss"], "y": ["input", "output"]},
            matrix=[[0.8, 0.2], [0.1, 0.9]],
            overall_risk=0.5,
            hotspots=[{"x": "sql", "y": "input", "risk": 0.8}],
        )
        assert len(heatmap.dimensions["x"]) == 2
        assert len(heatmap.matrix) == 2
        assert len(heatmap.hotspots) == 1


# ============================================================================
# GauntletComparison Model Tests
# ============================================================================


class TestGauntletComparisonModel:
    """Tests for GauntletComparison model."""

    def test_comparison_minimal(self):
        """Test GauntletComparison with required fields."""
        comparison = GauntletComparison(gauntlet_a="gnt-1", gauntlet_b="gnt-2")
        assert comparison.gauntlet_a == "gnt-1"
        assert comparison.gauntlet_b == "gnt-2"
        assert comparison.recommendation == "investigate"

    def test_comparison_full(self):
        """Test GauntletComparison with all data."""
        comparison = GauntletComparison(
            gauntlet_a="gnt-1",
            gauntlet_b="gnt-2",
            comparison={"risk_delta": -0.1, "new_findings": 2},
            scenario_diffs=[{"scenario": "sql", "delta": 0.2}],
            recommendation="promote",
        )
        assert comparison.comparison["risk_delta"] == -0.1
        assert len(comparison.scenario_diffs) == 1
        assert comparison.recommendation == "promote"


# ============================================================================
# GauntletAPI.run() Tests
# ============================================================================


class TestGauntletAPIRun:
    """Tests for GauntletAPI.run() method."""

    def test_run_basic(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test basic run() call."""
        mock_client._post.return_value = {
            "gauntlet_id": "gnt-123",
            "status": "pending",
        }

        result = gauntlet_api.run("Test content")

        assert result.gauntlet_id == "gnt-123"
        assert result.status == "pending"
        mock_client._post.assert_called_once()

    def test_run_with_options(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test run() with custom options."""
        mock_client._post.return_value = {
            "gauntlet_id": "gnt-456",
            "status": "running",
            "estimated_duration": 120,
        }

        result = gauntlet_api.run(
            input_content="Policy doc",
            input_type="policy",
            persona="gdpr",
            profile="thorough",
        )

        assert result.gauntlet_id == "gnt-456"
        assert result.estimated_duration == 120
        call_args = mock_client._post.call_args
        assert call_args[0][0] == "/api/gauntlet/run"
        payload = call_args[0][1]
        assert payload["input_type"] == "policy"
        assert payload["persona"] == "gdpr"
        assert payload["profile"] == "thorough"


class TestGauntletAPIRunAsync:
    """Tests for GauntletAPI.run_async() method."""

    @pytest.mark.asyncio
    async def test_run_async_basic(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test basic run_async() call."""
        mock_client._post_async = AsyncMock(
            return_value={
                "gauntlet_id": "gnt-async-123",
                "status": "pending",
            }
        )

        result = await gauntlet_api.run_async("Async content")

        assert result.gauntlet_id == "gnt-async-123"
        mock_client._post_async.assert_called_once()


# ============================================================================
# GauntletAPI.get_receipt() Tests
# ============================================================================


class TestGauntletAPIGetReceipt:
    """Tests for GauntletAPI.get_receipt() method."""

    def test_get_receipt_basic(
        self, gauntlet_api: GauntletAPI, mock_client: MagicMock, sample_timestamp: str
    ):
        """Test basic get_receipt() call."""
        mock_client._get.return_value = {
            "receipt_id": "rcpt-123",
            "gauntlet_id": "gnt-456",
            "verdict": "approved",
            "risk_score": 0.15,
            "findings": [],
            "created_at": sample_timestamp,
        }

        result = gauntlet_api.get_receipt("gnt-456")

        assert result.receipt_id == "rcpt-123"
        assert result.verdict == "approved"
        assert result.risk_score == 0.15
        mock_client._get.assert_called_once_with("/api/gauntlet/gnt-456/receipt")

    def test_get_receipt_with_findings(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test get_receipt() with findings."""
        mock_client._get.return_value = {
            "receipt_id": "rcpt-789",
            "gauntlet_id": "gnt-789",
            "verdict": "rejected",
            "risk_score": 0.85,
            "findings": [
                {"severity": "high", "title": "SQL Injection", "category": "security"},
                {"severity": "medium", "title": "XSS", "category": "security"},
            ],
        }

        result = gauntlet_api.get_receipt("gnt-789")

        assert result.verdict == "rejected"
        assert len(result.findings) == 2
        assert result.findings[0].severity == "high"


class TestGauntletAPIGetReceiptAsync:
    """Tests for GauntletAPI.get_receipt_async() method."""

    @pytest.mark.asyncio
    async def test_get_receipt_async(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test get_receipt_async() call."""
        mock_client._get_async = AsyncMock(
            return_value={
                "receipt_id": "rcpt-async",
                "gauntlet_id": "gnt-async",
                "verdict": "approved_with_conditions",
                "risk_score": 0.4,
                "findings": ["Minor issue"],
            }
        )

        result = await gauntlet_api.get_receipt_async("gnt-async")

        assert result.verdict == "approved_with_conditions"
        assert len(result.findings) == 1


# ============================================================================
# GauntletAPI.run_and_wait() Tests
# ============================================================================


class TestGauntletAPIRunAndWait:
    """Tests for GauntletAPI.run_and_wait() method."""

    def test_run_and_wait_immediate_success(
        self, gauntlet_api: GauntletAPI, mock_client: MagicMock
    ):
        """Test run_and_wait() when receipt is immediately available."""
        mock_client._post.return_value = {
            "gauntlet_id": "gnt-wait",
            "status": "running",
        }
        mock_client._get.side_effect = [
            {"gauntlet_id": "gnt-wait", "status": "completed"},
            {
                "receipt_id": "rcpt-wait",
                "gauntlet_id": "gnt-wait",
                "verdict": "approved",
                "risk_score": 0.1,
                "findings": [],
            },
        ]

        result = gauntlet_api.run_and_wait("Content to analyze")

        assert result.verdict == "approved"
        assert result.risk_score == 0.1

    def test_run_and_wait_polls_until_ready(
        self, gauntlet_api: GauntletAPI, mock_client: MagicMock
    ):
        """Test run_and_wait() polls when receipt not ready."""
        mock_client._post.return_value = {
            "gauntlet_id": "gnt-poll",
            "status": "running",
        }

        # Canonical run statuses precede the completed receipt.
        mock_client._get.side_effect = [
            {"gauntlet_id": "gnt-poll", "status": "running"},
            {"gauntlet_id": "gnt-poll", "status": "completed"},
            {
                "receipt_id": "rcpt-poll",
                "gauntlet_id": "gnt-poll",
                "verdict": "needs_review",
                "risk_score": 0.6,
                "findings": [],
            },
        ]

        with patch("time.sleep"):  # Speed up test
            result = gauntlet_api.run_and_wait("Polling content", timeout=60)

        assert result.verdict == "needs_review"
        assert mock_client._get.call_count == 3

    def test_run_and_wait_timeout(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test run_and_wait() raises TimeoutError."""
        mock_client._post.return_value = {
            "gauntlet_id": "gnt-timeout",
            "status": "running",
        }
        mock_client._get.return_value = {"gauntlet_id": "gnt-timeout", "status": "running"}

        with patch("time.sleep"):
            with patch("time.monotonic", side_effect=[0, 0, 100]):  # Simulate timeout
                with pytest.raises(TimeoutError) as exc:
                    gauntlet_api.run_and_wait("Timeout content", timeout=10)

        assert "gnt-timeout" in str(exc.value)

    def test_run_and_wait_non_404_error(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test run_and_wait() raises non-404 errors."""
        mock_client._post.return_value = {
            "gauntlet_id": "gnt-error",
            "status": "running",
        }
        error_500 = AragoraAPIError("Server error", status_code=500)
        mock_client._get.side_effect = error_500

        with pytest.raises(AragoraAPIError) as exc:
            gauntlet_api.run_and_wait("Error content")

        assert exc.value.status_code == 500


# ============================================================================
# GauntletAPI.get() Tests
# ============================================================================


class TestGauntletAPIGet:
    """Tests for GauntletAPI.get() method."""

    def test_get_run_status(
        self, gauntlet_api: GauntletAPI, mock_client: MagicMock, sample_timestamp: str
    ):
        """Test get() returns run status."""
        mock_client._get.return_value = {
            "id": "gnt-status",
            "name": "Security Check",
            "status": "running",
            "progress": {"completed": 75, "total": 100},
            "created_at": sample_timestamp,
        }

        result = gauntlet_api.get("gnt-status")

        assert result.id == "gnt-status"
        assert result.name == "Security Check"
        assert result.status == GauntletRunStatus.RUNNING
        assert result.progress["completed"] == 75
        mock_client._get.assert_called_once_with("/api/v1/gauntlet/gnt-status")


class TestGauntletAPIGetAsync:
    """Tests for GauntletAPI.get_async() method."""

    @pytest.mark.asyncio
    async def test_get_async(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test get_async() call."""
        mock_client._get_async = AsyncMock(
            return_value={
                "id": "gnt-async-status",
                "status": "completed",
            }
        )

        result = await gauntlet_api.get_async("gnt-async-status")

        assert result.id == "gnt-async-status"
        assert result.status == GauntletRunStatus.COMPLETED


# ============================================================================
# GauntletAPI.delete() Tests
# ============================================================================


class TestGauntletAPIDelete:
    """Tests for GauntletAPI.delete() method."""

    def test_delete_success(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test delete() returns success."""
        mock_client._delete.return_value = {"deleted": True}

        result = gauntlet_api.delete("gnt-delete")

        assert result["deleted"] is True
        mock_client._delete.assert_called_once_with("/api/v1/gauntlet/gnt-delete")

    def test_delete_implicit_success(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test delete() returns True when deleted not in response."""
        mock_client._delete.return_value = {}

        result = gauntlet_api.delete("gnt-delete-2")

        assert result["deleted"] is True


class TestGauntletAPIDeleteAsync:
    """Tests for GauntletAPI.delete_async() method."""

    @pytest.mark.asyncio
    async def test_delete_async(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test delete_async() call."""
        mock_client._delete_async = AsyncMock(return_value={"deleted": True})

        result = await gauntlet_api.delete_async("gnt-async-delete")

        assert result["deleted"] is True


# ============================================================================
# GauntletAPI.list_personas() Tests
# ============================================================================


class TestGauntletAPIListPersonas:
    """Tests for GauntletAPI.list_personas() method."""

    def test_list_personas_no_filter(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test list_personas() without filters."""
        mock_client._get.return_value = {
            "personas": [
                {"id": "p1", "name": "Security", "enabled": True},
                {"id": "p2", "name": "GDPR", "enabled": True},
            ]
        }

        result = gauntlet_api.list_personas()

        assert len(result) == 2
        assert result[0].id == "p1"
        mock_client._get.assert_called_once_with("/api/v1/gauntlet/personas", params={})

    def test_list_personas_with_category(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test list_personas() with category filter."""
        mock_client._get.return_value = [
            {"id": "p-adv", "name": "Adversary", "category": "adversarial"}
        ]

        result = gauntlet_api.list_personas(category="adversarial")

        assert len(result) == 1
        call_args = mock_client._get.call_args
        assert call_args[1]["params"]["category"] == "adversarial"

    def test_list_personas_with_enabled(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test list_personas() with enabled filter."""
        mock_client._get.return_value = {"personas": []}

        gauntlet_api.list_personas(enabled=False)

        call_args = mock_client._get.call_args
        assert call_args[1]["params"]["enabled"] is False


class TestGauntletAPIListPersonasAsync:
    """Tests for GauntletAPI.list_personas_async() method."""

    @pytest.mark.asyncio
    async def test_list_personas_async(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test list_personas_async() call."""
        mock_client._get_async = AsyncMock(
            return_value=[{"id": "p-async", "name": "Async Persona"}]
        )

        result = await gauntlet_api.list_personas_async(category="compliance")

        assert len(result) == 1
        assert result[0].id == "p-async"


# ============================================================================
# GauntletAPI.list_results() Tests
# ============================================================================


class TestGauntletAPIListResults:
    """Tests for GauntletAPI.list_results() method."""

    def test_list_results_basic(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test list_results() basic call."""
        mock_client._get.return_value = {
            "results": [
                {"id": "r1", "gauntlet_id": "g1", "status": "pass"},
                {"id": "r2", "gauntlet_id": "g1", "status": "fail"},
            ]
        }

        result = gauntlet_api.list_results()

        assert len(result) == 2
        assert result[0].status == GauntletResultStatus.PASS
        assert result[1].status == GauntletResultStatus.FAIL

    def test_list_results_with_filters(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test list_results() with filters."""
        mock_client._get.return_value = []

        gauntlet_api.list_results(gauntlet_id="g-filter", status="fail", limit=10, offset=5)

        call_args = mock_client._get.call_args
        params = call_args[1]["params"]
        assert params["gauntlet_id"] == "g-filter"
        assert params["status"] == "fail"
        assert params["limit"] == 10
        assert params["offset"] == 5


class TestGauntletAPIListResultsAsync:
    """Tests for GauntletAPI.list_results_async() method."""

    @pytest.mark.asyncio
    async def test_list_results_async(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test list_results_async() call."""
        mock_client._get_async = AsyncMock(
            return_value={"results": [{"id": "r-async", "gauntlet_id": "g-async"}]}
        )

        result = await gauntlet_api.list_results_async()

        assert len(result) == 1


# ============================================================================
# GauntletAPI.get_heatmap() Tests
# ============================================================================


class TestGauntletAPIGetHeatmap:
    """Tests for GauntletAPI.get_heatmap() method."""

    def test_get_heatmap_json(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test get_heatmap() with JSON format."""
        mock_client._get.return_value = {
            "gauntlet_id": "gnt-heatmap",
            "dimensions": {"x": ["a", "b"], "y": ["1", "2"]},
            "matrix": [[0.1, 0.2], [0.3, 0.4]],
            "overall_risk": 0.25,
            "hotspots": [],
        }

        result = gauntlet_api.get_heatmap("gnt-heatmap")

        assert result.gauntlet_id == "gnt-heatmap"
        assert result.overall_risk == 0.25
        assert len(result.matrix) == 2
        mock_client._get.assert_called_once_with(
            "/api/v1/gauntlet/gnt-heatmap/heatmap", params={"format": "json"}
        )

    def test_get_heatmap_svg(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test get_heatmap() with SVG format."""
        mock_client._get.return_value = {
            "gauntlet_id": "gnt-svg",
            "overall_risk": 0.5,
        }

        gauntlet_api.get_heatmap("gnt-svg", format="svg")

        call_args = mock_client._get.call_args
        assert call_args[1]["params"]["format"] == "svg"


class TestGauntletAPIGetHeatmapAsync:
    """Tests for GauntletAPI.get_heatmap_async() method."""

    @pytest.mark.asyncio
    async def test_get_heatmap_async(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test get_heatmap_async() call."""
        mock_client._get_async = AsyncMock(
            return_value={"gauntlet_id": "gnt-async-hm", "overall_risk": 0.3}
        )

        result = await gauntlet_api.get_heatmap_async("gnt-async-hm")

        assert result.gauntlet_id == "gnt-async-hm"


# ============================================================================
# GauntletAPI.compare() Tests
# ============================================================================


class TestGauntletAPICompare:
    """Tests for GauntletAPI.compare() method."""

    def test_compare_runs(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test compare() two gauntlet runs."""
        mock_client._get.return_value = {
            "gauntlet_a": "gnt-a",
            "gauntlet_b": "gnt-b",
            "comparison": {"risk_delta": -0.15, "findings_delta": 3},
            "scenario_diffs": [{"scenario": "sql", "improved": True}],
            "recommendation": "promote",
        }

        result = gauntlet_api.compare("gnt-a", "gnt-b")

        assert result.gauntlet_a == "gnt-a"
        assert result.gauntlet_b == "gnt-b"
        assert result.comparison["risk_delta"] == -0.15
        assert result.recommendation == "promote"
        mock_client._get.assert_called_once_with("/api/v1/gauntlet/gnt-a/compare/gnt-b")


class TestGauntletAPICompareAsync:
    """Tests for GauntletAPI.compare_async() method."""

    @pytest.mark.asyncio
    async def test_compare_async(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test compare_async() call."""
        mock_client._get_async = AsyncMock(
            return_value={
                "gauntlet_a": "gnt-async-a",
                "gauntlet_b": "gnt-async-b",
                "recommendation": "investigate",
            }
        )

        result = await gauntlet_api.compare_async("gnt-async-a", "gnt-async-b")

        assert result.recommendation == "investigate"


# ============================================================================
# Integration-like Tests
# ============================================================================


class TestGauntletAPIIntegration:
    """Integration-like tests for GauntletAPI."""

    def test_full_workflow(
        self, gauntlet_api: GauntletAPI, mock_client: MagicMock, sample_timestamp: str
    ):
        """Test full gauntlet workflow: run -> get status -> get receipt."""
        # Start run
        mock_client._post.return_value = {
            "gauntlet_id": "gnt-full",
            "status": "pending",
        }
        run_response = gauntlet_api.run("Full workflow test", persona="security")
        assert run_response.gauntlet_id == "gnt-full"

        # Check status
        mock_client._get.return_value = {
            "id": "gnt-full",
            "status": "completed",
            "progress": {"completed": 100, "total": 100},
        }
        status = gauntlet_api.get("gnt-full")
        assert status.status == GauntletRunStatus.COMPLETED

        # Get receipt
        mock_client._get.return_value = {
            "receipt_id": "rcpt-full",
            "gauntlet_id": "gnt-full",
            "verdict": "approved",
            "risk_score": 0.1,
            "findings": [],
            "created_at": sample_timestamp,
        }
        receipt = gauntlet_api.get_receipt("gnt-full")
        assert receipt.verdict == "approved"

    def test_comparison_workflow(self, gauntlet_api: GauntletAPI, mock_client: MagicMock):
        """Test running two gauntlets and comparing them."""
        # Run first gauntlet
        mock_client._post.return_value = {"gauntlet_id": "gnt-v1", "status": "pending"}
        run1 = gauntlet_api.run("Version 1 code", profile="quick")

        # Run second gauntlet
        mock_client._post.return_value = {"gauntlet_id": "gnt-v2", "status": "pending"}
        run2 = gauntlet_api.run("Version 2 code", profile="quick")

        # Compare
        mock_client._get.return_value = {
            "gauntlet_a": "gnt-v1",
            "gauntlet_b": "gnt-v2",
            "comparison": {"risk_improved": True},
            "recommendation": "promote",
        }
        comparison = gauntlet_api.compare(run1.gauntlet_id, run2.gauntlet_id)
        assert comparison.recommendation == "promote"
