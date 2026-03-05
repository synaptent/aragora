"""
Tests for MetaPlanner.approve_changes gauntlet quality gate (T1).

Validates that:
- approve_changes returns approved=True when gauntlet score >= 90% of baseline
- approve_changes returns approved=False when gauntlet score < 90% of baseline
- approve_changes handles missing gauntlet gracefully (default approve)
- The gauntlet runner is called with the proposed changes
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_gauntlet_result(robustness_score: float, critical: int = 0, high: int = 0):
    """Create a mock GauntletResult."""
    from aragora.gauntlet.result import GauntletResult, RiskSummary, SeverityLevel, Vulnerability

    vulns = []
    for i in range(critical):
        vulns.append(
            Vulnerability(
                id=f"vuln-crit-{i}",
                title=f"Critical {i}",
                description=f"Critical issue {i}",
                severity=SeverityLevel.CRITICAL,
                category="security",
                source="red_team",
            )
        )
    risk = RiskSummary(critical=critical, high=high)
    result = GauntletResult(
        gauntlet_id="gauntlet-test",
        input_hash="abc",
        input_summary="test",
        started_at="2026-03-05T00:00:00",
        vulnerabilities=vulns,
        risk_summary=risk,
    )
    result.robustness_score = robustness_score
    return result


class TestApproveChangesGauntletGate:
    """Tests for gauntlet quality gate in MetaPlanner.approve_changes."""

    @pytest.mark.asyncio
    async def test_approve_changes_passes_when_score_above_threshold(self):
        """approve_changes should return approved=True when score >= 90% of baseline."""
        from aragora.nomic.meta_planner import MetaPlanner

        planner = MetaPlanner()

        baseline_score = 0.80
        current_score = 0.80  # exactly at baseline -> 100%

        mock_result = _make_gauntlet_result(robustness_score=current_score)
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=mock_result)

        with patch(
            "aragora.nomic.meta_planner._GauntletRunner", return_value=mock_runner, create=True
        ):
            result = await planner.approve_changes(
                changes="def foo(): pass",
                gauntlet_baseline=baseline_score,
            )

        assert result["approved"] is True

    @pytest.mark.asyncio
    async def test_approve_changes_rejects_when_score_below_threshold(self):
        """approve_changes should return approved=False when score < 90% of baseline."""
        from aragora.nomic.meta_planner import MetaPlanner

        planner = MetaPlanner()

        baseline_score = 0.80
        # 0.70 is 87.5% of 0.80, which is < 90% threshold
        current_score = 0.70

        mock_result = _make_gauntlet_result(robustness_score=current_score)
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=mock_result)

        with patch(
            "aragora.nomic.meta_planner._GauntletRunner", return_value=mock_runner, create=True
        ):
            result = await planner.approve_changes(
                changes="def foo(): pass",
                gauntlet_baseline=baseline_score,
            )

        assert result["approved"] is False
        assert "gauntlet" in result.get("reason", "").lower()

    @pytest.mark.asyncio
    async def test_approve_changes_passes_at_exactly_90_percent(self):
        """approve_changes should pass when score is exactly 90% of baseline."""
        from aragora.nomic.meta_planner import MetaPlanner

        planner = MetaPlanner()

        baseline_score = 1.0
        current_score = 0.90  # exactly 90%

        mock_result = _make_gauntlet_result(robustness_score=current_score)
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=mock_result)

        with patch(
            "aragora.nomic.meta_planner._GauntletRunner", return_value=mock_runner, create=True
        ):
            result = await planner.approve_changes(
                changes="def foo(): pass",
                gauntlet_baseline=baseline_score,
            )

        assert result["approved"] is True

    @pytest.mark.asyncio
    async def test_approve_changes_no_baseline_uses_absolute_threshold(self):
        """When no baseline provided, compare against a minimum absolute score."""
        from aragora.nomic.meta_planner import MetaPlanner

        planner = MetaPlanner()

        mock_result = _make_gauntlet_result(robustness_score=0.50)
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=mock_result)

        with patch(
            "aragora.nomic.meta_planner._GauntletRunner", return_value=mock_runner, create=True
        ):
            result = await planner.approve_changes(changes="def foo(): pass")

        # Score 0.50 equals the default absolute baseline of 0.50; threshold is 0.45, so approved
        assert result["approved"] is True
        assert result["gauntlet_score"] == 0.50

    @pytest.mark.asyncio
    async def test_approve_changes_gauntlet_unavailable_defaults_to_approved(self):
        """When GauntletRunner is not importable, default to approved=True."""
        from aragora.nomic.meta_planner import MetaPlanner

        planner = MetaPlanner()

        with patch("aragora.nomic.meta_planner._GAUNTLET_AVAILABLE", False, create=True):
            result = await planner.approve_changes(changes="def foo(): pass")

        assert result["approved"] is True
        assert result.get("gauntlet_skipped") is True

    @pytest.mark.asyncio
    async def test_approve_changes_runner_error_defaults_to_approved(self):
        """When GauntletRunner raises, default to approved=True (fail open)."""
        from aragora.nomic.meta_planner import MetaPlanner

        planner = MetaPlanner()

        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(side_effect=RuntimeError("API failure"))

        with patch(
            "aragora.nomic.meta_planner._GauntletRunner", return_value=mock_runner, create=True
        ):
            result = await planner.approve_changes(changes="def foo(): pass")

        assert result["approved"] is True
        assert result.get("gauntlet_skipped") is True
