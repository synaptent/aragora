"""Tests for aragora.prediction.brier — per-agent rolling Brier scorer (AGT-04 / #6065)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aragora.prediction.brier import AgentBrierScore, compute_brier_scores
from aragora.prediction.stakeable_claim import (
    QuestionType,
    ResolutionStatus,
    StakeableClaim,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _claim(
    claim_id: str,
    *,
    status: ResolutionStatus = ResolutionStatus.RESOLVED_YES,
    positions: dict[str, float] | None = None,
    created_at: datetime | None = None,
) -> StakeableClaim:
    ts = created_at or datetime.now(tz=UTC)
    return StakeableClaim(
        claim_id=claim_id,
        question=f"Will PR #{claim_id} merge?",
        question_type=QuestionType.PR_MERGE,
        target_ref=f"synaptent/aragora#{claim_id}",
        expiry=(ts + timedelta(days=30)).isoformat(),
        resolution_status=status,
        resolution_value=(status == ResolutionStatus.RESOLVED_YES),
        positions=positions or {},
        created_at=ts.isoformat(),
    )


# ---------------------------------------------------------------------------
# Feature-flag tests
# ---------------------------------------------------------------------------


class TestFeatureFlag:
    def test_raises_when_flag_off(self, monkeypatch):
        monkeypatch.delenv("ARAGORA_PREDICTION_MARKETS_ENABLED", raising=False)
        with pytest.raises(RuntimeError, match="disabled"):
            compute_brier_scores([])

    def test_require_enabled_false_bypasses_flag(self, monkeypatch):
        monkeypatch.delenv("ARAGORA_PREDICTION_MARKETS_ENABLED", raising=False)
        result = compute_brier_scores([], require_enabled=False)
        assert result == {}

    def test_flag_on_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_PREDICTION_MARKETS_ENABLED", "1")
        result = compute_brier_scores([])
        assert result == {}


# ---------------------------------------------------------------------------
# Score arithmetic
# ---------------------------------------------------------------------------


class TestScoreArithmetic:
    def test_perfect_score_yes(self):
        c = _claim("c1", status=ResolutionStatus.RESOLVED_YES, positions={"a": 1.0})
        result = compute_brier_scores([c], require_enabled=False)
        assert result["a"].score == pytest.approx(0.0)

    def test_perfect_score_no(self):
        c = _claim("c1", status=ResolutionStatus.RESOLVED_NO, positions={"a": 0.0})
        result = compute_brier_scores([c], require_enabled=False)
        assert result["a"].score == pytest.approx(0.0)

    def test_no_skill_baseline_half(self):
        c = _claim("c1", status=ResolutionStatus.RESOLVED_YES, positions={"a": 0.5})
        result = compute_brier_scores([c], require_enabled=False)
        assert result["a"].score == pytest.approx(0.25)

    def test_average_over_multiple_claims(self):
        # Perfect on YES (0), worst on NO (1) → average 0.5
        c1 = _claim("c1", status=ResolutionStatus.RESOLVED_YES, positions={"a": 1.0})
        c2 = _claim("c2", status=ResolutionStatus.RESOLVED_NO, positions={"a": 1.0})
        result = compute_brier_scores([c1, c2], require_enabled=False)
        assert result["a"].score == pytest.approx(0.5)
        assert result["a"].n_predictions == 2

    def test_multiple_agents_scored_independently(self):
        c = _claim("c1", status=ResolutionStatus.RESOLVED_YES, positions={"a": 1.0, "b": 0.0})
        result = compute_brier_scores([c], require_enabled=False)
        assert result["a"].score == pytest.approx(0.0)
        assert result["b"].score == pytest.approx(1.0)

    def test_four_predictions_known_average(self):
        # (0.8-1)^2=0.04, (0.6-1)^2=0.16, (0.4-0)^2=0.16, (0.2-0)^2=0.04 → mean=0.10
        now = datetime.now(tz=UTC)
        claims = [
            _claim(
                "c1", status=ResolutionStatus.RESOLVED_YES, positions={"a": 0.8}, created_at=now
            ),
            _claim(
                "c2", status=ResolutionStatus.RESOLVED_YES, positions={"a": 0.6}, created_at=now
            ),
            _claim("c3", status=ResolutionStatus.RESOLVED_NO, positions={"a": 0.4}, created_at=now),
            _claim("c4", status=ResolutionStatus.RESOLVED_NO, positions={"a": 0.2}, created_at=now),
        ]
        result = compute_brier_scores(claims, require_enabled=False)
        assert result["a"].score == pytest.approx(0.10)
        assert result["a"].n_predictions == 4


# ---------------------------------------------------------------------------
# Claim filtering
# ---------------------------------------------------------------------------


class TestClaimFiltering:
    def test_open_claims_excluded(self):
        c = _claim("c1", status=ResolutionStatus.OPEN, positions={"a": 0.8})
        assert compute_brier_scores([c], require_enabled=False) == {}

    def test_expired_claims_excluded(self):
        c = _claim("c1", status=ResolutionStatus.EXPIRED, positions={"a": 0.8})
        assert compute_brier_scores([c], require_enabled=False) == {}

    def test_inconclusive_claims_excluded(self):
        c = _claim("c1", status=ResolutionStatus.INCONCLUSIVE, positions={"a": 0.8})
        assert compute_brier_scores([c], require_enabled=False) == {}

    def test_no_positions_agent_absent_from_result(self):
        c = _claim("c1", status=ResolutionStatus.RESOLVED_YES, positions={})
        assert compute_brier_scores([c], require_enabled=False) == {}

    def test_old_claim_outside_window_excluded(self):
        old = datetime(2020, 1, 1, tzinfo=UTC)
        c = _claim("c1", status=ResolutionStatus.RESOLVED_YES, positions={"a": 1.0}, created_at=old)
        assert compute_brier_scores([c], window_days=90, require_enabled=False) == {}

    def test_recent_claim_inside_window_included(self):
        recent = datetime.now(tz=UTC) - timedelta(days=10)
        c = _claim(
            "c1", status=ResolutionStatus.RESOLVED_YES, positions={"a": 1.0}, created_at=recent
        )
        result = compute_brier_scores([c], window_days=90, require_enabled=False)
        assert "a" in result

    def test_future_claim_above_cutoff_excluded(self):
        cutoff = datetime.now(tz=UTC)
        future = cutoff + timedelta(days=5)
        c = _claim(
            "c1", status=ResolutionStatus.RESOLVED_YES, positions={"a": 1.0}, created_at=future
        )
        result = compute_brier_scores([c], cutoff_dt=cutoff, require_enabled=False)
        assert result == {}


# ---------------------------------------------------------------------------
# AgentBrierScore dataclass
# ---------------------------------------------------------------------------


class TestAgentBrierScore:
    def test_has_skill_below_025(self):
        c = _claim("c1", status=ResolutionStatus.RESOLVED_YES, positions={"a": 0.9})
        score = compute_brier_scores([c], require_enabled=False)["a"]
        assert score.score == pytest.approx(0.01)
        assert score.has_skill is True

    def test_no_skill_at_025(self):
        c = _claim("c1", status=ResolutionStatus.RESOLVED_YES, positions={"a": 0.5})
        score = compute_brier_scores([c], require_enabled=False)["a"]
        assert score.has_skill is False

    def test_to_dict_keys(self):
        c = _claim("c1", status=ResolutionStatus.RESOLVED_YES, positions={"a": 1.0})
        d = compute_brier_scores([c], require_enabled=False)["a"].to_dict()
        assert set(d.keys()) == {"agent_id", "score", "n_predictions", "window_days", "computed_at"}

    def test_to_dict_values(self):
        c = _claim("c1", status=ResolutionStatus.RESOLVED_YES, positions={"a": 1.0})
        d = compute_brier_scores([c], window_days=45, require_enabled=False)["a"].to_dict()
        assert d["agent_id"] == "a"
        assert d["score"] == pytest.approx(0.0)
        assert d["n_predictions"] == 1
        assert d["window_days"] == 45
