"""
Comprehensive tests for aragora.debate.phases.voting module.

Covers:
- VoteWeightCalculator: single source, multiple sources, caching, batch, error handling
- VotingPhase.group_similar_votes: no grouping, single group, multiple groups, below threshold
- VotingPhase.apply_vote_grouping: normalization, no groups
- VotingPhase.compute_vote_distribution: empty, single choice, multiple choices, confidence averaging
- VotingPhase.determine_winner: simple plurality, majority requirement, margin requirement, tie
- VotingPhase.count_weighted_votes: unweighted, weighted, with user votes, with grouping
- VotingPhase.compute_consensus_strength: unanimous, strong, medium, weak
- VotingPhase.check_unanimous: all same, dissent, with errors
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from aragora.debate.phases.voting import (
    VoteWeightCalculator,
    VotingPhase,
    WeightedVoteResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeVote:
    """Lightweight stand-in for aragora.core.Vote."""

    agent: str
    choice: str
    reasoning: str = "because"
    confidence: float | None = 0.9


def _make_protocol(
    *, vote_grouping: bool = False, threshold: float = 0.85, consensus_threshold: float = 0.6
):
    """Return a mock DebateProtocol with the attributes VotingPhase reads."""
    proto = MagicMock()
    proto.vote_grouping = vote_grouping
    proto.vote_grouping_threshold = threshold
    proto.consensus_threshold = consensus_threshold
    return proto


def _make_backend(similarity_map: dict[tuple[str, str], float] | None = None):
    """Return a mock SimilarityBackend whose compute_similarity looks up a dict."""
    backend = MagicMock()
    _map = similarity_map or {}

    def _sim(a: str, b: str) -> float:
        return _map.get((a, b), _map.get((b, a), 0.0))

    backend.compute_similarity.side_effect = _sim
    return backend


# ============================================================================
# VoteWeightCalculator tests
# ============================================================================


class TestVoteWeightCalculator:
    """Tests for VoteWeightCalculator."""

    def test_no_sources_returns_one(self):
        """With no weight sources the weight is 1.0."""
        calc = VoteWeightCalculator()
        assert calc.compute_weight("alice") == 1.0

    def test_reputation_source_only(self):
        """Single reputation source multiplies into weight."""
        calc = VoteWeightCalculator(reputation_source=lambda name: 1.2)
        assert calc.compute_weight("bob") == pytest.approx(1.2)

    def test_reliability_weights_only(self):
        """Pre-computed reliability dict is used as multiplier."""
        calc = VoteWeightCalculator(reliability_weights={"carol": 0.8})
        assert calc.compute_weight("carol") == pytest.approx(0.8)
        # Unknown agent falls back to 1.0 (no entry in dict)
        assert calc.compute_weight("unknown") == pytest.approx(1.0)

    def test_consistency_source_maps_score(self):
        """Consistency score 0-1 is mapped to 0.5-1.0 multiplier."""
        # score=1.0 -> multiplier = 0.5 + 0.5*1.0 = 1.0
        calc = VoteWeightCalculator(consistency_source=lambda _: 1.0)
        assert calc.compute_weight("x") == pytest.approx(1.0)

        # score=0.0 -> multiplier = 0.5
        calc2 = VoteWeightCalculator(consistency_source=lambda _: 0.0)
        calc2.clear_cache()
        assert calc2.compute_weight("x") == pytest.approx(0.5)

    def test_calibration_source_only(self):
        """Calibration source is used as a direct multiplier."""
        calc = VoteWeightCalculator(calibration_source=lambda _: 1.3)
        assert calc.compute_weight("y") == pytest.approx(1.3)

    def test_multiple_sources_multiply(self):
        """All sources combine multiplicatively."""
        calc = VoteWeightCalculator(
            reputation_source=lambda _: 1.2,
            reliability_weights={"agent": 0.9},
            consistency_source=lambda _: 0.8,  # -> 0.5 + 0.4 = 0.9
            calibration_source=lambda _: 1.1,
        )
        expected = 1.2 * 0.9 * 0.9 * 1.1
        assert calc.compute_weight("agent") == pytest.approx(expected)

    def test_caching(self):
        """Second call for the same agent returns cached value."""
        call_count = 0

        def _rep(name: str) -> float:
            nonlocal call_count
            call_count += 1
            return 1.5

        calc = VoteWeightCalculator(reputation_source=_rep)
        first = calc.compute_weight("z")
        second = calc.compute_weight("z")
        assert first == second == pytest.approx(1.5)
        assert call_count == 1  # source only called once

    def test_clear_cache(self):
        """clear_cache forces recomputation on next call."""
        counter = {"n": 0}

        def _rep(name: str) -> float:
            counter["n"] += 1
            return 1.0 + counter["n"] * 0.1

        calc = VoteWeightCalculator(reputation_source=_rep)
        v1 = calc.compute_weight("a")
        calc.clear_cache()
        v2 = calc.compute_weight("a")
        assert v1 != v2
        assert counter["n"] == 2

    def test_batch(self):
        """compute_weights_batch returns dict for all requested agents."""
        calc = VoteWeightCalculator(
            reliability_weights={"a": 0.7, "b": 1.0, "c": 0.5},
        )
        result = calc.compute_weights_batch(["a", "b", "c", "d"])
        assert result == pytest.approx({"a": 0.7, "b": 1.0, "c": 0.5, "d": 1.0})

    def test_source_error_is_swallowed(self):
        """If a source raises a handled exception, the weight defaults to 1.0 for that source."""
        calc = VoteWeightCalculator(
            reputation_source=lambda _: (_ for _ in ()).throw(ValueError("boom")),
            calibration_source=lambda _: 1.4,
        )
        # reputation fails -> 1.0, calibration -> 1.4
        assert calc.compute_weight("err") == pytest.approx(1.4)


# ============================================================================
# VotingPhase.group_similar_votes tests
# ============================================================================


class TestGroupSimilarVotes:
    """Tests for VotingPhase.group_similar_votes."""

    def test_grouping_disabled(self):
        """Returns empty dict when vote_grouping is False."""
        proto = _make_protocol(vote_grouping=False)
        vp = VotingPhase(proto)
        votes = [FakeVote("a", "X"), FakeVote("b", "Y")]
        assert vp.group_similar_votes(votes) == {}

    def test_empty_votes(self):
        """Returns empty dict for no votes."""
        proto = _make_protocol(vote_grouping=True)
        vp = VotingPhase(proto)
        assert vp.group_similar_votes([]) == {}

    def test_single_unique_choice(self):
        """Single unique choice produces no groups (need 2+ to group)."""
        proto = _make_protocol(vote_grouping=True)
        backend = _make_backend()
        vp = VotingPhase(proto, similarity_backend=backend)
        votes = [FakeVote("a", "X"), FakeVote("b", "X")]
        assert vp.group_similar_votes(votes) == {}

    def test_single_group_formed(self):
        """Two similar choices get grouped under the first as canonical."""
        proto = _make_protocol(vote_grouping=True, threshold=0.8)
        backend = _make_backend({("Vector DB", "Use vector database"): 0.95})
        vp = VotingPhase(proto, similarity_backend=backend)
        votes = [FakeVote("a", "Vector DB"), FakeVote("b", "Use vector database")]
        groups = vp.group_similar_votes(votes)
        # One group mapping the canonical choice to both variants
        assert len(groups) == 1
        canonical = list(groups.keys())[0]
        assert len(groups[canonical]) == 2

    def test_below_threshold_not_grouped(self):
        """Choices with similarity below threshold are not grouped."""
        proto = _make_protocol(vote_grouping=True, threshold=0.9)
        backend = _make_backend({("A", "B"): 0.5})
        vp = VotingPhase(proto, similarity_backend=backend)
        votes = [FakeVote("x", "A"), FakeVote("y", "B")]
        assert vp.group_similar_votes(votes) == {}

    def test_multiple_groups(self):
        """Distinct clusters form separate groups."""
        proto = _make_protocol(vote_grouping=True, threshold=0.8)
        backend = _make_backend(
            {
                ("A1", "A2"): 0.95,
                ("B1", "B2"): 0.90,
                ("A1", "B1"): 0.1,
                ("A1", "B2"): 0.1,
                ("A2", "B1"): 0.1,
                ("A2", "B2"): 0.1,
            }
        )
        vp = VotingPhase(proto, similarity_backend=backend)
        votes = [
            FakeVote("a", "A1"),
            FakeVote("b", "A2"),
            FakeVote("c", "B1"),
            FakeVote("d", "B2"),
        ]
        groups = vp.group_similar_votes(votes)
        assert len(groups) == 2
        all_members = []
        for members in groups.values():
            all_members.extend(members)
        assert set(all_members) == {"A1", "A2", "B1", "B2"}


# ============================================================================
# VotingPhase.apply_vote_grouping tests
# ============================================================================


class TestApplyVoteGrouping:
    """Tests for VotingPhase.apply_vote_grouping."""

    def test_no_groups_returns_original(self):
        """Empty groups dict returns original vote list."""
        vp = VotingPhase(_make_protocol())
        votes = [FakeVote("a", "X")]
        result = vp.apply_vote_grouping(votes, {})
        assert result is votes

    def test_normalization(self):
        """Votes whose choice is a group variant get the canonical choice."""
        vp = VotingPhase(_make_protocol())
        groups = {"canonical": ["canonical", "variant1", "variant2"]}
        votes = [
            FakeVote("a", "variant1"),
            FakeVote("b", "variant2"),
            FakeVote("c", "unrelated"),
        ]
        result = vp.apply_vote_grouping(votes, groups)
        assert result[0].choice == "canonical"
        assert result[1].choice == "canonical"
        assert result[2].choice == "unrelated"


# ============================================================================
# VotingPhase.compute_vote_distribution tests
# ============================================================================


class TestComputeVoteDistribution:
    """Tests for VotingPhase.compute_vote_distribution."""

    def test_empty_votes(self):
        """Empty list yields empty distribution."""
        vp = VotingPhase(_make_protocol())
        assert vp.compute_vote_distribution([]) == {}

    def test_single_choice(self):
        """All votes on one choice -> 100%."""
        vp = VotingPhase(_make_protocol())
        votes = [FakeVote("a", "X", confidence=0.8), FakeVote("b", "X", confidence=1.0)]
        dist = vp.compute_vote_distribution(votes)
        assert "X" in dist
        assert dist["X"]["count"] == 2
        assert dist["X"]["percentage"] == pytest.approx(100.0)
        assert set(dist["X"]["voters"]) == {"a", "b"}
        assert dist["X"]["avg_confidence"] == pytest.approx(0.9)

    def test_multiple_choices(self):
        """Distribution reflects proportional counts."""
        vp = VotingPhase(_make_protocol())
        votes = [
            FakeVote("a", "X"),
            FakeVote("b", "X"),
            FakeVote("c", "Y"),
            FakeVote("d", "Z"),
        ]
        dist = vp.compute_vote_distribution(votes)
        assert dist["X"]["count"] == 2
        assert dist["X"]["percentage"] == pytest.approx(50.0)
        assert dist["Y"]["count"] == 1
        assert dist["Y"]["percentage"] == pytest.approx(25.0)

    def test_confidence_averaging_with_none(self):
        """Votes with None confidence are excluded from average."""
        vp = VotingPhase(_make_protocol())
        votes = [
            FakeVote("a", "X", confidence=0.6),
            FakeVote("b", "X", confidence=None),
        ]
        dist = vp.compute_vote_distribution(votes)
        assert dist["X"]["avg_confidence"] == pytest.approx(0.6)


# ============================================================================
# VotingPhase.determine_winner tests
# ============================================================================


class TestDetermineWinner:
    """Tests for VotingPhase.determine_winner."""

    def test_simple_plurality(self):
        """Most votes wins in simple mode."""
        vp = VotingPhase(_make_protocol())
        votes = [FakeVote("a", "X"), FakeVote("b", "X"), FakeVote("c", "Y")]
        assert vp.determine_winner(votes) == "X"

    def test_empty_votes_returns_none(self):
        """No votes -> None."""
        vp = VotingPhase(_make_protocol())
        assert vp.determine_winner([]) is None

    def test_majority_requirement_met(self):
        """Winner returned when majority is achieved."""
        vp = VotingPhase(_make_protocol())
        votes = [FakeVote("a", "X"), FakeVote("b", "X"), FakeVote("c", "Y")]
        # X has 66.7% > 50%
        assert vp.determine_winner(votes, require_majority=True) == "X"

    def test_majority_requirement_not_met(self):
        """None returned when no choice exceeds 50%."""
        vp = VotingPhase(_make_protocol())
        votes = [
            FakeVote("a", "X"),
            FakeVote("b", "Y"),
            FakeVote("c", "Z"),
            FakeVote("d", "X"),
        ]
        # X has 50% exactly, which is <= 50 (strict check)
        assert vp.determine_winner(votes, require_majority=True) is None

    def test_min_margin_met(self):
        """Winner returned when margin exceeds threshold."""
        vp = VotingPhase(_make_protocol())
        # X=3, Y=1 -> pct X=75, pct Y=25, margin=(75-25)/100=0.5
        votes = [FakeVote("a", "X"), FakeVote("b", "X"), FakeVote("c", "X"), FakeVote("d", "Y")]
        assert vp.determine_winner(votes, min_margin=0.3) == "X"

    def test_min_margin_not_met(self):
        """None returned when margin is below threshold."""
        vp = VotingPhase(_make_protocol())
        # X=2, Y=1 -> margin=(66.7-33.3)/100 ~= 0.333
        votes = [FakeVote("a", "X"), FakeVote("b", "X"), FakeVote("c", "Y")]
        assert vp.determine_winner(votes, min_margin=0.5) is None


# ============================================================================
# VotingPhase.count_weighted_votes tests
# ============================================================================


class TestCountWeightedVotes:
    """Tests for VotingPhase.count_weighted_votes."""

    def test_unweighted(self):
        """Without a weight_calculator, all agents have weight 1.0."""
        vp = VotingPhase(_make_protocol())
        votes = [FakeVote("a", "X"), FakeVote("b", "X"), FakeVote("c", "Y")]
        result = vp.count_weighted_votes(votes)
        assert result.winner == "X"
        assert result.vote_counts["X"] == pytest.approx(2.0)
        assert result.vote_counts["Y"] == pytest.approx(1.0)
        assert result.total_weighted_votes == pytest.approx(3.0)
        assert result.confidence == pytest.approx(2.0 / 3.0)

    def test_weighted(self):
        """Weight calculator scales individual votes."""
        vp = VotingPhase(_make_protocol())
        calc = VoteWeightCalculator(reliability_weights={"a": 0.5, "b": 2.0, "c": 1.0})
        votes = [FakeVote("a", "X"), FakeVote("b", "Y"), FakeVote("c", "Y")]
        result = vp.count_weighted_votes(votes, weight_calculator=calc)
        # X: 0.5, Y: 2.0 + 1.0 = 3.0
        assert result.winner == "Y"
        assert result.vote_counts["X"] == pytest.approx(0.5)
        assert result.vote_counts["Y"] == pytest.approx(3.0)

    def test_with_user_votes(self):
        """User votes are added with user_vote_weight."""
        vp = VotingPhase(_make_protocol())
        votes = [FakeVote("a", "X"), FakeVote("b", "Y")]
        user_votes = [{"choice": "Y", "user_id": "u1"}]
        result = vp.count_weighted_votes(votes, user_votes=user_votes, user_vote_weight=0.5)
        assert result.vote_counts["Y"] == pytest.approx(1.5)  # 1.0 + 0.5
        assert result.total_weighted_votes == pytest.approx(2.5)

    def test_with_missing_user_vote_entries(self):
        """Missing entries in a user-vote batch do not abort aggregation."""
        vp = VotingPhase(_make_protocol())
        votes = [FakeVote("a", "X")]
        user_votes = [None, {"choice": "X", "user_id": "u1"}]

        result = vp.count_weighted_votes(votes, user_votes=user_votes, user_vote_weight=0.5)

        assert result.vote_counts["X"] == pytest.approx(1.5)
        assert result.total_weighted_votes == pytest.approx(1.5)

    def test_with_user_vote_multiplier(self):
        """User vote multiplier scales user weight by intensity."""
        vp = VotingPhase(_make_protocol())
        votes = [FakeVote("a", "X")]
        user_votes = [{"choice": "X", "intensity": 10}]

        def multiplier(intensity, protocol):
            return intensity / 5.0  # 10/5 = 2.0

        result = vp.count_weighted_votes(
            votes,
            user_votes=user_votes,
            user_vote_weight=0.5,
            user_vote_multiplier=multiplier,
        )
        # agent: 1.0, user: 0.5 * 2.0 = 1.0
        assert result.vote_counts["X"] == pytest.approx(2.0)

    def test_with_grouping(self):
        """Vote grouping merges similar choices before counting."""
        proto = _make_protocol(vote_grouping=True, threshold=0.8)
        backend = _make_backend({("Accept", "Approve"): 0.95})
        vp = VotingPhase(proto, similarity_backend=backend)
        votes = [
            FakeVote("a", "Accept"),
            FakeVote("b", "Approve"),
            FakeVote("c", "Reject"),
        ]
        result = vp.count_weighted_votes(votes)
        # Accept and Approve are grouped; canonical may be either due to set ordering
        grouped_canonical = result.winner
        assert grouped_canonical in ("Accept", "Approve")
        assert result.vote_counts[grouped_canonical] == pytest.approx(2.0)
        assert result.vote_counts["Reject"] == pytest.approx(1.0)

    def test_empty_votes(self):
        """Empty vote list returns default result."""
        vp = VotingPhase(_make_protocol())
        result = vp.count_weighted_votes([])
        assert result.winner is None
        assert result.total_weighted_votes == 0.0


# ============================================================================
# VotingPhase.compute_consensus_strength tests
# ============================================================================


class TestComputeConsensusStrength:
    """Tests for VotingPhase.compute_consensus_strength."""

    def test_empty_counts(self):
        """Empty counts -> 'none'."""
        vp = VotingPhase(_make_protocol())
        info = vp.compute_consensus_strength({}, 0.0)
        assert info["strength"] == "none"
        assert info["variance"] == 0.0

    def test_unanimous(self):
        """Single choice -> 'unanimous'."""
        vp = VotingPhase(_make_protocol())
        info = vp.compute_consensus_strength({"X": 5.0}, 5.0)
        assert info["strength"] == "unanimous"
        assert info["variance"] == 0.0

    def test_strong(self):
        """Variance < 1 -> 'strong'."""
        vp = VotingPhase(_make_protocol())
        # counts [3, 3] -> mean=3, variance=0
        info = vp.compute_consensus_strength({"X": 3.0, "Y": 3.0}, 6.0)
        assert info["strength"] == "strong"
        assert info["variance"] == pytest.approx(0.0)

    def test_medium(self):
        """1 <= variance < 2 -> 'medium'."""
        vp = VotingPhase(_make_protocol())
        # counts [4, 2] -> mean=3, variance = ((1)^2 + (-1)^2)/2 = 1.0
        info = vp.compute_consensus_strength({"X": 4.0, "Y": 2.0}, 6.0)
        assert info["strength"] == "medium"
        assert info["variance"] == pytest.approx(1.0)

    def test_weak(self):
        """Variance >= 2 -> 'weak'."""
        vp = VotingPhase(_make_protocol())
        # counts [5, 1] -> mean=3, variance = (4+4)/2 = 4.0
        info = vp.compute_consensus_strength({"X": 5.0, "Y": 1.0}, 6.0)
        assert info["strength"] == "weak"
        assert info["variance"] == pytest.approx(4.0)


# ============================================================================
# VotingPhase.check_unanimous tests
# ============================================================================


class TestCheckUnanimous:
    """Tests for VotingPhase.check_unanimous."""

    def test_all_same_choice(self):
        """All agents vote the same -> unanimous consensus."""
        vp = VotingPhase(_make_protocol())
        votes = [FakeVote("a", "X"), FakeVote("b", "X"), FakeVote("c", "X")]
        result = vp.check_unanimous(votes)
        assert result.consensus_reached is True
        assert result.consensus_strength == "unanimous"
        assert result.winner == "X"
        assert result.confidence == pytest.approx(1.0)

    def test_dissenting_vote(self):
        """One dissenter blocks unanimity."""
        vp = VotingPhase(_make_protocol())
        votes = [FakeVote("a", "X"), FakeVote("b", "X"), FakeVote("c", "Y")]
        result = vp.check_unanimous(votes)
        assert result.consensus_reached is False
        assert result.winner == "X"
        assert result.confidence == pytest.approx(2 / 3)

    def test_voting_errors_count_as_dissent(self):
        """voting_errors inflate total, preventing unanimity even with one choice."""
        vp = VotingPhase(_make_protocol())
        votes = [FakeVote("a", "X"), FakeVote("b", "X")]
        result = vp.check_unanimous(votes, voting_errors=1)
        # total_voters = 2 valid + 1 error = 3; 2/3 < 1.0
        assert result.consensus_reached is False
        assert result.confidence == pytest.approx(2 / 3)

    def test_empty_votes(self):
        """Empty votes list returns default result."""
        vp = VotingPhase(_make_protocol())
        result = vp.check_unanimous([])
        assert result.winner is None
        assert result.consensus_reached is False

    def test_unanimity_with_grouping(self):
        """Vote grouping allows unanimity when variants map to same canonical."""
        proto = _make_protocol(vote_grouping=True, threshold=0.8)
        backend = _make_backend({("Yes", "Approve"): 0.95})
        vp = VotingPhase(proto, similarity_backend=backend)
        votes = [FakeVote("a", "Yes"), FakeVote("b", "Approve")]
        result = vp.check_unanimous(votes)
        assert result.consensus_reached is True
        assert result.consensus_strength == "unanimous"
