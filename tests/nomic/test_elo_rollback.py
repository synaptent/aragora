"""
Tests for ELO regression detection in MetaPlanner.approve_changes (T2).

Validates that:
- approve_changes returns approved=False when avg ELO < 95% of baseline
- approve_changes returns approved=True when avg ELO >= 95% of baseline
- ELO gate composes correctly with gauntlet gate (both must pass)
- Missing ELO data fails gracefully (default approve)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_elo_system(avg_elo: float):
    """Create a mock EloSystem returning given average ELO across all agents."""
    from aragora.ranking.elo import AgentRating

    ratings = [
        AgentRating(agent_name="claude", elo=avg_elo),
        AgentRating(agent_name="codex", elo=avg_elo),
    ]
    elo = MagicMock()
    elo.get_all_ratings.return_value = ratings
    return elo


class TestApproveChangesEloGate:
    """Tests for ELO regression detection in MetaPlanner.approve_changes."""

    @pytest.mark.asyncio
    async def test_approve_passes_when_elo_above_threshold(self):
        """approve_changes should pass when avg ELO >= 95% of baseline."""
        from aragora.nomic.meta_planner import MetaPlanner

        planner = MetaPlanner()

        baseline_elo = 1200.0
        current_avg_elo = 1200.0  # 100%, well above 95%

        mock_elo = _make_mock_elo_system(current_avg_elo)

        with patch("aragora.nomic.meta_planner._get_elo_store", return_value=mock_elo, create=True):
            result = await planner.approve_changes(
                changes="def foo(): pass",
                elo_baseline=baseline_elo,
            )

        assert result["approved"] is True

    @pytest.mark.asyncio
    async def test_approve_rejects_when_elo_below_threshold(self):
        """approve_changes should return approved=False when avg ELO < 95% of baseline."""
        from aragora.nomic.meta_planner import MetaPlanner

        planner = MetaPlanner()

        baseline_elo = 1200.0
        # 1130 is ~94.2% of 1200 — below the 95% threshold
        current_avg_elo = 1130.0

        mock_elo = _make_mock_elo_system(current_avg_elo)

        with patch("aragora.nomic.meta_planner._get_elo_store", return_value=mock_elo, create=True):
            result = await planner.approve_changes(
                changes="def foo(): pass",
                elo_baseline=baseline_elo,
            )

        assert result["approved"] is False
        assert "elo" in result.get("reason", "").lower()

    @pytest.mark.asyncio
    async def test_approve_passes_at_exactly_95_percent(self):
        """approve_changes should pass when avg ELO is exactly 95% of baseline."""
        from aragora.nomic.meta_planner import MetaPlanner

        planner = MetaPlanner()

        baseline_elo = 1000.0
        current_avg_elo = 950.0  # exactly 95%

        mock_elo = _make_mock_elo_system(current_avg_elo)

        with patch("aragora.nomic.meta_planner._get_elo_store", return_value=mock_elo, create=True):
            result = await planner.approve_changes(
                changes="def foo(): pass",
                elo_baseline=baseline_elo,
            )

        assert result["approved"] is True

    @pytest.mark.asyncio
    async def test_approve_elo_unavailable_defaults_to_approved(self):
        """When EloSystem is not available, default to approved=True."""
        from aragora.nomic.meta_planner import MetaPlanner

        planner = MetaPlanner()

        with patch(
            "aragora.nomic.meta_planner._get_elo_store",
            side_effect=ImportError("no elo"),
            create=True,
        ):
            result = await planner.approve_changes(
                changes="def foo(): pass",
                elo_baseline=1200.0,
            )

        assert result["approved"] is True

    @pytest.mark.asyncio
    async def test_approve_no_ratings_defaults_to_approved(self):
        """When ELO store has no ratings, skip check and approve."""
        from aragora.nomic.meta_planner import MetaPlanner

        planner = MetaPlanner()

        mock_elo = MagicMock()
        mock_elo.get_all_ratings.return_value = []

        with patch("aragora.nomic.meta_planner._get_elo_store", return_value=mock_elo, create=True):
            result = await planner.approve_changes(
                changes="def foo(): pass",
                elo_baseline=1200.0,
            )

        assert result["approved"] is True

    @pytest.mark.asyncio
    async def test_both_gates_must_pass(self):
        """When both gauntlet and ELO baselines given, both must pass."""
        from aragora.nomic.meta_planner import MetaPlanner

        planner = MetaPlanner()

        # ELO passes, gauntlet fails
        mock_elo = _make_mock_elo_system(avg_elo=1200.0)

        from aragora.gauntlet.result import GauntletResult, RiskSummary

        bad_gauntlet_result = GauntletResult(
            gauntlet_id="test",
            input_hash="abc",
            input_summary="test",
            started_at="2026-03-05T00:00:00",
        )
        bad_gauntlet_result.robustness_score = 0.50  # 50% of baseline=1.0 -> fails

        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=bad_gauntlet_result)

        with (
            patch("aragora.nomic.meta_planner._get_elo_store", return_value=mock_elo, create=True),
            patch(
                "aragora.nomic.meta_planner._GauntletRunner", return_value=mock_runner, create=True
            ),
        ):
            result = await planner.approve_changes(
                changes="def foo(): pass",
                elo_baseline=1200.0,
                gauntlet_baseline=1.0,
            )

        assert result["approved"] is False
        assert "gauntlet" in result.get("reason", "").lower()
