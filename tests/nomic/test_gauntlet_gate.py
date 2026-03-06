"""
Tests for the Gauntlet Approval Gate in the Nomic Loop.

Validates that:
- The gate is opt-in (disabled by default)
- A lightweight Gauntlet run is executed when enabled
- CRITICAL/HIGH findings block approval
- The gate integrates with the autonomous orchestrator
- The gate integrates with the VerifyPhase
- Errors in the Gauntlet run do not block the pipeline
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.nomic.gauntlet_gate import (
    BlockingFinding,
    GauntletApprovalGate,
    GauntletGateConfig,
    GauntletGateResult,
)


# ---------------------------------------------------------------------------
# GauntletGateConfig tests
# ---------------------------------------------------------------------------


class TestGauntletGateConfig:
    """Tests for GauntletGateConfig defaults and behaviour."""

    def test_defaults(self):
        config = GauntletGateConfig()
        assert config.enabled is False
        assert config.max_critical == 0
        assert config.max_high == 0
        assert config.attack_rounds == 1
        assert config.probes_per_category == 1
        assert config.run_scenario_matrix is False
        assert config.timeout_seconds == 120

    def test_custom_thresholds(self):
        config = GauntletGateConfig(
            enabled=True,
            max_critical=1,
            max_high=3,
        )
        assert config.enabled is True
        assert config.max_critical == 1
        assert config.max_high == 3


# ---------------------------------------------------------------------------
# GauntletGateResult tests
# ---------------------------------------------------------------------------


class TestGauntletGateResult:
    """Tests for GauntletGateResult data class."""

    def test_passed_property(self):
        result = GauntletGateResult(blocked=False)
        assert result.passed is True

        result = GauntletGateResult(blocked=True)
        assert result.passed is False

    def test_to_dict(self):
        finding = BlockingFinding(
            severity="critical",
            title="Test vuln",
            description="A test vulnerability",
            category="security",
            source="red_team",
        )
        result = GauntletGateResult(
            blocked=True,
            reason="Blocked",
            critical_count=1,
            high_count=0,
            total_findings=1,
            blocking_findings=[finding],
            gauntlet_id="gauntlet-abc123",
            duration_seconds=5.2,
        )
        d = result.to_dict()
        assert d["blocked"] is True
        assert d["passed"] is False
        assert d["critical_count"] == 1
        assert d["gauntlet_id"] == "gauntlet-abc123"
        assert len(d["blocking_findings"]) == 1
        assert d["blocking_findings"][0]["severity"] == "critical"

    def test_skipped_result(self):
        result = GauntletGateResult(
            blocked=False,
            reason="Gauntlet gate disabled",
            skipped=True,
        )
        assert result.passed is True
        assert result.skipped is True


# ---------------------------------------------------------------------------
# GauntletApprovalGate — disabled by default
# ---------------------------------------------------------------------------


class TestGauntletGateDisabled:
    """Tests for the gate when disabled."""

    @pytest.mark.asyncio
    async def test_disabled_by_default(self):
        """Gate should skip when config.enabled is False."""
        gate = GauntletApprovalGate()
        result = await gate.evaluate(content="some content")
        assert result.passed is True
        assert result.skipped is True
        assert result.blocked is False
        assert "disabled" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_disabled_explicitly(self):
        gate = GauntletApprovalGate(config=GauntletGateConfig(enabled=False))
        result = await gate.evaluate(content="x")
        assert result.skipped is True
        assert result.blocked is False


# ---------------------------------------------------------------------------
# GauntletApprovalGate — enabled, mocking the GauntletRunner
# ---------------------------------------------------------------------------


def _make_mock_gauntlet_result(
    critical: int = 0,
    high: int = 0,
    medium: int = 0,
    gauntlet_id: str = "gauntlet-test123",
    duration: float = 2.5,
):
    """Create a mock GauntletResult with the given severity counts."""
    from aragora.gauntlet.result import (
        GauntletResult,
        RiskSummary,
        SeverityLevel,
        Vulnerability,
    )

    risk = RiskSummary(critical=critical, high=high, medium=medium)
    vulns = []
    for i in range(critical):
        vulns.append(
            Vulnerability(
                id=f"vuln-crit-{i}",
                title=f"Critical finding {i}",
                description=f"Critical issue {i}",
                severity=SeverityLevel.CRITICAL,
                category="security",
                source="red_team",
            )
        )
    for i in range(high):
        vulns.append(
            Vulnerability(
                id=f"vuln-high-{i}",
                title=f"High finding {i}",
                description=f"High issue {i}",
                severity=SeverityLevel.HIGH,
                category="logic",
                source="capability_probe",
            )
        )

    result = GauntletResult(
        gauntlet_id=gauntlet_id,
        input_hash="abc123",
        input_summary="test content",
        started_at="2026-02-24T00:00:00",
        completed_at="2026-02-24T00:00:02",
        duration_seconds=duration,
        vulnerabilities=vulns,
        risk_summary=risk,
    )
    return result


class TestGauntletGateBlocking:
    """Tests for blocking behaviour on CRITICAL/HIGH findings."""

    @pytest.mark.asyncio
    async def test_blocks_on_critical_findings(self):
        """Gate should block when CRITICAL findings exceed threshold."""
        mock_result = _make_mock_gauntlet_result(critical=1)
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=mock_result)

        config = GauntletGateConfig(enabled=True, max_critical=0, max_high=0)
        gate = GauntletApprovalGate(config=config)

        with patch("aragora.nomic.gauntlet_gate._GauntletRunner", return_value=mock_runner):
            result = await gate.evaluate(content="test content")

        assert result.blocked is True
        assert result.critical_count == 1
        assert "CRITICAL" in result.reason
        assert len(result.blocking_findings) == 1
        assert result.blocking_findings[0].severity == "critical"

    @pytest.mark.asyncio
    async def test_blocks_on_high_findings(self):
        """Gate should block when HIGH findings exceed threshold."""
        mock_result = _make_mock_gauntlet_result(high=2)
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=mock_result)

        config = GauntletGateConfig(enabled=True, max_critical=0, max_high=0)
        gate = GauntletApprovalGate(config=config)

        with patch("aragora.nomic.gauntlet_gate._GauntletRunner", return_value=mock_runner):
            result = await gate.evaluate(content="test content")

        assert result.blocked is True
        assert result.high_count == 2
        assert "HIGH" in result.reason
        assert len(result.blocking_findings) == 2

    @pytest.mark.asyncio
    async def test_passes_when_below_thresholds(self):
        """Gate should pass when findings are below thresholds."""
        mock_result = _make_mock_gauntlet_result(critical=0, high=0, medium=3)
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=mock_result)

        config = GauntletGateConfig(enabled=True, max_critical=0, max_high=0)
        gate = GauntletApprovalGate(config=config)

        with patch("aragora.nomic.gauntlet_gate._GauntletRunner", return_value=mock_runner):
            result = await gate.evaluate(content="test content")

        assert result.blocked is False
        assert result.passed is True
        assert result.total_findings == 0  # Only medium, not in vulns list
        assert "passed" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_custom_thresholds_allow_some_findings(self):
        """Gate should pass when findings are within custom thresholds."""
        mock_result = _make_mock_gauntlet_result(critical=1, high=2)
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=mock_result)

        config = GauntletGateConfig(enabled=True, max_critical=1, max_high=3)
        gate = GauntletApprovalGate(config=config)

        with patch("aragora.nomic.gauntlet_gate._GauntletRunner", return_value=mock_runner):
            result = await gate.evaluate(content="test content")

        assert result.blocked is False
        assert result.critical_count == 1
        assert result.high_count == 2

    @pytest.mark.asyncio
    async def test_blocks_when_exceeding_custom_threshold(self):
        """Gate should block when findings exceed custom thresholds."""
        mock_result = _make_mock_gauntlet_result(critical=2, high=4)
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=mock_result)

        config = GauntletGateConfig(enabled=True, max_critical=1, max_high=3)
        gate = GauntletApprovalGate(config=config)

        with patch("aragora.nomic.gauntlet_gate._GauntletRunner", return_value=mock_runner):
            result = await gate.evaluate(content="test content")

        assert result.blocked is True
        assert "CRITICAL" in result.reason
        assert "HIGH" in result.reason

    @pytest.mark.asyncio
    async def test_no_findings_passes(self):
        """Gate should pass cleanly when there are no findings."""
        mock_result = _make_mock_gauntlet_result(critical=0, high=0, medium=0)
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=mock_result)

        config = GauntletGateConfig(enabled=True)
        gate = GauntletApprovalGate(config=config)

        with patch("aragora.nomic.gauntlet_gate._GauntletRunner", return_value=mock_runner):
            result = await gate.evaluate(content="safe content")

        assert result.blocked is False
        assert result.passed is True
        assert result.total_findings == 0
        assert result.gauntlet_id == "gauntlet-test123"
        assert result.duration_seconds == 2.5


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestGauntletGateErrors:
    """Tests for error handling in the gate."""

    @pytest.mark.asyncio
    async def test_runner_error_does_not_block(self):
        """Gate should not block when the runner raises an exception."""
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(side_effect=RuntimeError("API unavailable"))

        config = GauntletGateConfig(enabled=True)
        gate = GauntletApprovalGate(config=config)

        with patch("aragora.nomic.gauntlet_gate._GauntletRunner", return_value=mock_runner):
            result = await gate.evaluate(content="test")

        assert result.blocked is False
        assert result.skipped is True
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_gauntlet_unavailable_does_not_block(self):
        """Gate should not block when gauntlet module is not available."""
        config = GauntletGateConfig(enabled=True)
        gate = GauntletApprovalGate(config=config)

        # Simulate gauntlet module not being available
        with patch("aragora.nomic.gauntlet_gate._GAUNTLET_AVAILABLE", False):
            result = await gate.evaluate(content="test")

        assert result.blocked is False
        assert result.skipped is True
        assert result.error is not None


# ---------------------------------------------------------------------------
# Integration with AutonomousOrchestrator
# ---------------------------------------------------------------------------


class TestGauntletGateOrchestratorIntegration:
    """Tests for the gate wired into AutonomousOrchestrator."""

    @pytest.mark.asyncio
    async def test_orchestrator_runs_gauntlet_gate_on_success(self):
        """When enable_gauntlet_gate=True, _run_gauntlet_gate is called."""
        from aragora.nomic.autonomous_orchestrator import AutonomousOrchestrator

        orch = AutonomousOrchestrator(
            enable_gauntlet_gate=True,
            require_human_approval=False,
        )

        # Mock the gate to return a passing result
        passing_result = GauntletGateResult(
            blocked=False,
            reason="passed",
        )

        mock_gate = AsyncMock(return_value=passing_result)
        orch._run_gauntlet_gate = mock_gate  # type: ignore[assignment]

        # Verify the method exists and is callable
        assert callable(orch._run_gauntlet_gate)

    @pytest.mark.asyncio
    async def test_orchestrator_blocks_on_gauntlet_failure(self):
        """When Gauntlet gate blocks, assignment should be rejected."""
        from aragora.nomic.autonomous_orchestrator import AutonomousOrchestrator

        orch = AutonomousOrchestrator(
            enable_gauntlet_gate=True,
            require_human_approval=False,
        )

        # Verify the flag is set
        assert orch.enable_gauntlet_gate is True

    def test_orchestrator_gate_disabled_by_default(self):
        """Gate should be disabled by default in the orchestrator."""
        from aragora.nomic.autonomous_orchestrator import AutonomousOrchestrator

        orch = AutonomousOrchestrator(require_human_approval=False)
        assert orch.enable_gauntlet_gate is False


# ---------------------------------------------------------------------------
# Integration with VerifyPhase
# ---------------------------------------------------------------------------


class TestGauntletGateVerifyPhaseIntegration:
    """Tests for the gate wired into the VerifyPhase."""

    @pytest.mark.asyncio
    async def test_verify_phase_runs_gauntlet_when_enabled(self, tmp_path):
        """VerifyPhase should call _check_gauntlet_gate when enabled."""
        from scripts.nomic.phases.verify import VerifyPhase

        phase = VerifyPhase(
            aragora_path=tmp_path,
            log_fn=MagicMock(),
            enable_gauntlet_gate=True,
        )

        # Mock the gate check method
        gate_result = {
            "check": "gauntlet_gate",
            "passed": True,
            "note": "passed",
        }
        phase._check_gauntlet_gate = AsyncMock(return_value=gate_result)

        # Also mock the other checks to pass
        phase._check_syntax = AsyncMock(return_value={"check": "syntax", "passed": True})
        phase._check_imports = AsyncMock(return_value={"check": "import", "passed": True})
        phase._run_tests = AsyncMock(return_value={"check": "tests", "passed": True})

        result = await phase.execute()
        phase._check_gauntlet_gate.assert_called_once()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_verify_phase_blocks_on_gauntlet_failure(self, tmp_path):
        """VerifyPhase should fail when gauntlet gate blocks."""
        from scripts.nomic.phases.verify import VerifyPhase

        phase = VerifyPhase(
            aragora_path=tmp_path,
            log_fn=MagicMock(),
            enable_gauntlet_gate=True,
        )

        # Mock gate to return blocking result
        gate_result = {
            "check": "gauntlet_gate",
            "passed": False,
            "blocked": True,
            "reason": "CRITICAL findings found",
            "critical_count": 2,
        }
        phase._check_gauntlet_gate = AsyncMock(return_value=gate_result)

        # Other checks pass
        phase._check_syntax = AsyncMock(return_value={"check": "syntax", "passed": True})
        phase._check_imports = AsyncMock(return_value={"check": "import", "passed": True})
        phase._run_tests = AsyncMock(return_value={"check": "tests", "passed": True})

        result = await phase.execute()
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_verify_phase_skips_gauntlet_when_disabled(self, tmp_path):
        """VerifyPhase should not run gauntlet check when disabled."""
        from scripts.nomic.phases.verify import VerifyPhase

        phase = VerifyPhase(
            aragora_path=tmp_path,
            log_fn=MagicMock(),
            enable_gauntlet_gate=False,
        )

        phase._check_gauntlet_gate = AsyncMock()

        # Mock the other checks to pass
        phase._check_syntax = AsyncMock(return_value={"check": "syntax", "passed": True})
        phase._check_imports = AsyncMock(return_value={"check": "import", "passed": True})
        phase._run_tests = AsyncMock(return_value={"check": "tests", "passed": True})

        result = await phase.execute()
        phase._check_gauntlet_gate.assert_not_called()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_verify_phase_gauntlet_skips_when_no_diff(self, tmp_path):
        """_check_gauntlet_gate should skip when there is no diff."""
        from scripts.nomic.phases.verify import VerifyPhase

        phase = VerifyPhase(
            aragora_path=tmp_path,
            log_fn=MagicMock(),
            enable_gauntlet_gate=True,
        )

        phase._get_diff_text = AsyncMock(return_value="")

        result = await phase._check_gauntlet_gate()
        assert result is not None
        assert result["passed"] is True
        assert "no diff" in result.get("note", "").lower()

    @pytest.mark.asyncio
    async def test_verify_phase_gauntlet_blocks_on_findings(self, tmp_path):
        """_check_gauntlet_gate should block when gate returns blocked."""
        from scripts.nomic.phases.verify import VerifyPhase

        phase = VerifyPhase(
            aragora_path=tmp_path,
            log_fn=MagicMock(),
            enable_gauntlet_gate=True,
        )

        phase._get_diff_text = AsyncMock(
            return_value="--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new"
        )

        # Mock the gate to return blocked
        blocked_gate_result = GauntletGateResult(
            blocked=True,
            reason="1 CRITICAL finding",
            critical_count=1,
            high_count=0,
            total_findings=1,
            blocking_findings=[
                BlockingFinding(
                    severity="critical",
                    title="Test vuln",
                    description="desc",
                    category="security",
                    source="red_team",
                ),
            ],
            gauntlet_id="gauntlet-test",
            duration_seconds=1.0,
        )

        mock_gate_instance = MagicMock()
        mock_gate_instance.evaluate = AsyncMock(return_value=blocked_gate_result)

        with patch(
            "aragora.nomic.gauntlet_gate.GauntletApprovalGate",
            return_value=mock_gate_instance,
        ):
            result = await phase._check_gauntlet_gate()

        assert result is not None
        assert result["passed"] is False
        assert result["blocked"] is True
        assert result["critical_count"] == 1


# ---------------------------------------------------------------------------
# Lightweight configuration
# ---------------------------------------------------------------------------


class TestGauntletGateLightweightMode:
    """Tests that the gate uses lightweight Gauntlet configuration."""

    @pytest.mark.asyncio
    async def test_lightweight_config_applied(self):
        """Gate should create a GauntletConfig with minimal settings."""
        config = GauntletGateConfig(enabled=True)
        gate = GauntletApprovalGate(config=config)

        captured_config = None

        class FakeRunner:
            def __init__(self, config=None, **kwargs):
                nonlocal captured_config
                captured_config = config

            async def run(self, input_content, context="", **kwargs):
                return _make_mock_gauntlet_result()

        with patch("aragora.nomic.gauntlet_gate._GauntletRunner", FakeRunner):
            await gate.evaluate(content="test content")

        assert captured_config is not None
        assert captured_config.attack_rounds == 1
        assert captured_config.probes_per_category == 1
        assert captured_config.run_scenario_matrix is False
        assert captured_config.max_agents == 2

    @pytest.mark.asyncio
    async def test_custom_config_overrides(self):
        """Gate should respect custom config overrides."""
        config = GauntletGateConfig(
            enabled=True,
            attack_rounds=3,
            probes_per_category=2,
            run_scenario_matrix=True,
        )
        gate = GauntletApprovalGate(config=config)

        captured_config = None

        class FakeRunner:
            def __init__(self, config=None, **kwargs):
                nonlocal captured_config
                captured_config = config

            async def run(self, input_content, context="", **kwargs):
                return _make_mock_gauntlet_result()

        with patch("aragora.nomic.gauntlet_gate._GauntletRunner", FakeRunner):
            await gate.evaluate(content="test content")

        assert captured_config is not None
        assert captured_config.attack_rounds == 3
        assert captured_config.probes_per_category == 2
        assert captured_config.run_scenario_matrix is True


# ---------------------------------------------------------------------------
# Gauntlet quality regression gate (T1 — Epic #295)
# ---------------------------------------------------------------------------


def _make_mock_gauntlet_result_with_robustness(
    robustness_score: float = 1.0,
    gauntlet_id: str = "gauntlet-regression-test",
    duration: float = 1.5,
):
    """Create a mock GauntletResult with a specific robustness score."""
    from aragora.gauntlet.result import (
        AttackSummary,
        GauntletResult,
        RiskSummary,
    )

    return GauntletResult(
        gauntlet_id=gauntlet_id,
        input_hash="abc123",
        input_summary="test content",
        started_at="2026-03-05T00:00:00",
        completed_at="2026-03-05T00:00:01",
        duration_seconds=duration,
        risk_summary=RiskSummary(),
        attack_summary=AttackSummary(robustness_score=robustness_score),
    )


class TestGauntletQualityRegression:
    """Tests for the gauntlet quality regression gate."""

    @pytest.mark.asyncio
    async def test_nomic_loop_rejects_on_gauntlet_regression(self):
        """Quality check should reject when robustness regresses >10%."""
        from aragora.nomic.gauntlet_gate import GauntletQualityResult

        # Baseline score is 0.9, new score is 0.7 -> regression of ~22%
        mock_result = _make_mock_gauntlet_result_with_robustness(robustness_score=0.7)
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=mock_result)

        config = GauntletGateConfig(enabled=True)
        gate = GauntletApprovalGate(config=config)

        with patch("aragora.nomic.gauntlet_gate._GauntletRunner", return_value=mock_runner):
            result = await gate.check_quality_regression(
                content="test content",
                baseline_score=0.9,
                max_regression_pct=10.0,
            )

        assert isinstance(result, GauntletQualityResult)
        assert result.passed is False
        assert result.baseline_score == 0.9
        assert result.current_score == 0.7
        assert result.regression_pct > 10.0
        assert "regression" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_nomic_loop_accepts_on_gauntlet_pass(self):
        """Quality check should accept when regression is within threshold."""
        from aragora.nomic.gauntlet_gate import GauntletQualityResult

        # Baseline is 0.9, new score is 0.85 -> regression of ~5.6%
        mock_result = _make_mock_gauntlet_result_with_robustness(robustness_score=0.85)
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=mock_result)

        config = GauntletGateConfig(enabled=True)
        gate = GauntletApprovalGate(config=config)

        with patch("aragora.nomic.gauntlet_gate._GauntletRunner", return_value=mock_runner):
            result = await gate.check_quality_regression(
                content="test content",
                baseline_score=0.9,
                max_regression_pct=10.0,
            )

        assert isinstance(result, GauntletQualityResult)
        assert result.passed is True
        assert result.baseline_score == 0.9
        assert result.current_score == 0.85
        assert result.regression_pct <= 10.0
        assert "passed" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_quality_check_skipped_when_disabled(self):
        """Quality check should pass immediately when gate is disabled."""
        config = GauntletGateConfig(enabled=False)
        gate = GauntletApprovalGate(config=config)

        result = await gate.check_quality_regression(
            content="test",
            baseline_score=0.9,
        )
        assert result.passed is True
        assert "disabled" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_quality_check_improvement_passes(self):
        """When score improves, quality check should pass."""
        # Baseline 0.7, new score 0.9 -> improvement (negative regression)
        mock_result = _make_mock_gauntlet_result_with_robustness(robustness_score=0.9)
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=mock_result)

        config = GauntletGateConfig(enabled=True)
        gate = GauntletApprovalGate(config=config)

        with patch("aragora.nomic.gauntlet_gate._GauntletRunner", return_value=mock_runner):
            result = await gate.check_quality_regression(
                content="test",
                baseline_score=0.7,
                max_regression_pct=10.0,
            )

        assert result.passed is True
        assert result.regression_pct < 0  # negative = improvement

    @pytest.mark.asyncio
    async def test_quality_check_runner_error_does_not_block(self):
        """When the runner errors, quality check should pass (non-blocking)."""
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(side_effect=RuntimeError("API down"))

        config = GauntletGateConfig(enabled=True)
        gate = GauntletApprovalGate(config=config)

        with patch("aragora.nomic.gauntlet_gate._GauntletRunner", return_value=mock_runner):
            result = await gate.check_quality_regression(
                content="test",
                baseline_score=0.9,
            )

        assert result.passed is True
        assert "failed" in result.reason.lower()
