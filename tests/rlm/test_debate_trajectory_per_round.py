"""Tests for DebateTrajectoryCollector per-round recording."""

from __future__ import annotations

import pytest

from aragora.rlm.debate_integration import (
    DebateOutcome,
    DebateTrajectoryCollector,
    reset_debate_trajectory_collector,
)


@pytest.fixture
def collector():
    return DebateTrajectoryCollector(max_trajectories=100)


class TestRecordRound:
    def test_outcome_normalizes_explicit_none_agents(self):
        outcome = DebateOutcome(
            debate_id="d1",
            task="Test task",
            consensus_reached=True,
            confidence=0.9,
            agents=None,  # type: ignore[arg-type]
        )

        assert outcome.agents == []

    def test_record_round_creates_steps(self, collector):
        """Per-round data should create proposal and critique steps."""
        collector.record_round(
            debate_id="d1",
            round_num=0,
            proposals=[{"agent": "alice", "content": "My proposal"}],
            critiques=[{"agent": "bob", "content": "I disagree"}],
            convergence_similarity=0.3,
        )

        trajectory = collector._in_progress["d1"]
        assert len(trajectory.steps) == 2
        assert trajectory.steps[0].action_type == "proposal"
        assert trajectory.steps[0].action == "My proposal"
        assert trajectory.steps[0].state["round"] == 0
        assert trajectory.steps[0].state["convergence"] == 0.3
        assert trajectory.steps[1].action_type == "critique"

    def test_multiple_rounds_accumulate(self, collector):
        """Multiple round recordings for same debate should accumulate steps."""
        collector.record_round(
            debate_id="d1",
            round_num=0,
            proposals=[{"agent": "a", "content": "p1"}],
            critiques=[{"agent": "b", "content": "c1"}],
        )
        collector.record_round(
            debate_id="d1",
            round_num=1,
            proposals=[{"agent": "a", "content": "p2"}],
            critiques=[{"agent": "b", "content": "c2"}],
        )

        trajectory = collector._in_progress["d1"]
        assert len(trajectory.steps) == 4
        assert trajectory.steps[2].state["round"] == 1

    def test_record_round_then_finalize(self, collector):
        """record_debate_outcome should merge in-progress per-round steps."""
        collector.record_round(
            debate_id="d1",
            round_num=0,
            proposals=[{"agent": "a", "content": "round 0 proposal"}],
            critiques=[],
        )

        trajectory = collector.record_debate_outcome(
            debate_id="d1",
            task="Test task",
            consensus_reached=True,
            confidence=0.9,
        )

        # Per-round step should be prepended
        assert trajectory.steps[0].action_type == "proposal"
        assert trajectory.steps[0].action == "round 0 proposal"
        # In-progress should be cleaned up
        assert "d1" not in collector._in_progress

    def test_record_round_empty_debate_id_ignored(self, collector):
        """Empty debate_id should be silently ignored."""
        collector.record_round(
            debate_id="",
            round_num=0,
            proposals=[{"agent": "a", "content": "test"}],
            critiques=[],
        )
        assert len(collector._in_progress) == 0

    def test_finalize_without_rounds(self, collector):
        """record_debate_outcome works normally when no per-round data exists."""
        trajectory = collector.record_debate_outcome(
            debate_id="d2",
            task="No rounds",
            consensus_reached=False,
            confidence=0.5,
        )
        assert trajectory is not None
        assert trajectory.trajectory_id == "d2"

    def test_content_truncated_to_500(self, collector):
        """Proposal/critique content longer than 500 chars should be truncated."""
        long_content = "x" * 1000
        collector.record_round(
            debate_id="d1",
            round_num=0,
            proposals=[{"agent": "a", "content": long_content}],
            critiques=[],
        )
        assert len(collector._in_progress["d1"].steps[0].action) == 500
