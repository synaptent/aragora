"""Tests for aragora.reputation.suspension_policy (AGT-05 #6066 sub-6).

All tests run without network access. The feature flag is toggled via
monkeypatch so the global environment is never mutated between tests.
"""

from __future__ import annotations

import os
import pytest

from aragora.reputation.store import ReputationStore
from aragora.reputation.suspension_policy import (
    DEFAULT_MIN_SAMPLES,
    DEFAULT_SCORE_FLOOR,
    DEFAULT_SUSPENSION_DAYS,
    SuspensionChecker,
    SuspensionDecision,
    SuspensionThreshold,
    enable_suspension,
    suspension_enabled,
)
from aragora.reputation.types import ReputationDelta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FLAG = "ARAGORA_REPUTATION_SUSPENSION_ENABLED"


def _delta(
    agent_id: str = "agent-a",
    *,
    delta: float = -10.0,
    domain: str = "prediction_market",
    idx: int = 0,
) -> ReputationDelta:
    return ReputationDelta(
        delta_id=f"rep_{agent_id}_{domain}_{idx:04d}",
        agent_id=agent_id,
        domain=domain,
        claim_id=f"claim-{idx}",
        resolution_id=f"res-{idx}",
        delta=delta,
        scoring_rule="binary",
        applied_at="2026-07-01T00:00:00Z",
        decay_half_life_days=None,
        reason={"idx": idx},
    )


def _store_with_deltas(
    agent_id: str = "agent-a",
    *,
    count: int = 10,
    delta_value: float = -10.0,
    domain: str = "prediction_market",
) -> ReputationStore:
    store = ReputationStore()
    for i in range(count):
        store.record_delta(_delta(agent_id, delta=delta_value, domain=domain, idx=i))
    return store


# ---------------------------------------------------------------------------
# Feature-flag tests
# ---------------------------------------------------------------------------


def test_flag_off_by_default(monkeypatch):
    monkeypatch.delenv(_FLAG, raising=False)
    assert not suspension_enabled()


def test_enable_suspension_sets_flag(monkeypatch):
    monkeypatch.delenv(_FLAG, raising=False)
    enable_suspension()
    assert suspension_enabled()
    monkeypatch.delenv(_FLAG, raising=False)


def test_flag_disabled_returns_not_suspended(monkeypatch):
    monkeypatch.delenv(_FLAG, raising=False)
    checker = SuspensionChecker()
    store = _store_with_deltas(count=20, delta_value=-100.0)
    decision = checker.check("agent-a", store)
    assert not decision.suspended
    assert decision.reason == "flag_disabled"
    assert decision.score is None
    assert decision.sample_count == 0


# ---------------------------------------------------------------------------
# SuspensionThreshold validation
# ---------------------------------------------------------------------------


def test_default_threshold_values():
    t = SuspensionThreshold()
    assert t.score_floor == DEFAULT_SCORE_FLOOR
    assert t.min_samples == DEFAULT_MIN_SAMPLES
    assert t.suspension_days == DEFAULT_SUSPENSION_DAYS
    assert t.domains is None


def test_threshold_rejects_zero_min_samples():
    with pytest.raises(ValueError, match="min_samples must be >= 1"):
        SuspensionThreshold(min_samples=0)


def test_threshold_rejects_negative_suspension_days():
    with pytest.raises(ValueError, match="suspension_days must be > 0"):
        SuspensionThreshold(suspension_days=-1.0)


# ---------------------------------------------------------------------------
# Fingerprint determinism
# ---------------------------------------------------------------------------


def test_fingerprint_deterministic():
    t1 = SuspensionThreshold(score_floor=-50.0, min_samples=10, suspension_days=7.0)
    t2 = SuspensionThreshold(score_floor=-50.0, min_samples=10, suspension_days=7.0)
    assert t1.fingerprint() == t2.fingerprint()


def test_fingerprint_changes_with_floor():
    t1 = SuspensionThreshold(score_floor=-50.0)
    t2 = SuspensionThreshold(score_floor=-100.0)
    assert t1.fingerprint() != t2.fingerprint()


def test_fingerprint_changes_with_domains():
    t1 = SuspensionThreshold(domains=None)
    t2 = SuspensionThreshold(domains=frozenset({"prediction_market"}))
    assert t1.fingerprint() != t2.fingerprint()


def test_fingerprint_domain_order_independent():
    t1 = SuspensionThreshold(domains=frozenset({"a", "b"}))
    t2 = SuspensionThreshold(domains=frozenset({"b", "a"}))
    assert t1.fingerprint() == t2.fingerprint()


def test_fingerprint_is_64_hex_chars():
    assert len(SuspensionThreshold().fingerprint()) == 64


# ---------------------------------------------------------------------------
# SuspensionDecision.to_dict
# ---------------------------------------------------------------------------


def test_to_dict_has_expected_keys(monkeypatch):
    monkeypatch.setenv(_FLAG, "1")
    checker = SuspensionChecker()
    store = _store_with_deltas(count=12, delta_value=-10.0)
    decision = checker.check("agent-a", store)
    d = decision.to_dict()
    for key in (
        "agent_id",
        "suspended",
        "reason",
        "score",
        "sample_count",
        "threshold_fingerprint",
        "decided_at",
        "suspension_days",
    ):
        assert key in d, f"missing key: {key}"


# ---------------------------------------------------------------------------
# no-data path
# ---------------------------------------------------------------------------


def test_no_data_returns_not_suspended(monkeypatch):
    monkeypatch.setenv(_FLAG, "1")
    checker = SuspensionChecker()
    store = ReputationStore()  # empty
    decision = checker.check("agent-unknown", store)
    assert not decision.suspended
    assert decision.reason == "no_data"
    assert decision.score is None
    assert decision.sample_count == 0


def test_no_data_with_domain_filter(monkeypatch):
    monkeypatch.setenv(_FLAG, "1")
    # Agent has deltas in one domain, but filter asks for a different domain.
    store = _store_with_deltas(count=15, delta_value=-10.0, domain="code_pr")
    threshold = SuspensionThreshold(
        domains=frozenset({"prediction_market"}),
        min_samples=5,
    )
    checker = SuspensionChecker(threshold=threshold)
    decision = checker.check("agent-a", store)
    assert not decision.suspended
    assert decision.reason == "no_data"


# ---------------------------------------------------------------------------
# insufficient_samples path
# ---------------------------------------------------------------------------


def test_insufficient_samples_not_suspended(monkeypatch):
    monkeypatch.setenv(_FLAG, "1")
    threshold = SuspensionThreshold(min_samples=10, score_floor=-5.0)
    checker = SuspensionChecker(threshold=threshold)
    # Only 5 deltas, each -10: score would be -50 (below floor), but sample count too low.
    store = _store_with_deltas(count=5, delta_value=-10.0)
    decision = checker.check("agent-a", store)
    assert not decision.suspended
    assert decision.reason == "insufficient_samples"
    assert decision.sample_count == 5
    assert decision.score is not None


# ---------------------------------------------------------------------------
# score_above_floor path
# ---------------------------------------------------------------------------


def test_score_above_floor_not_suspended(monkeypatch):
    monkeypatch.setenv(_FLAG, "1")
    threshold = SuspensionThreshold(score_floor=-100.0, min_samples=5)
    checker = SuspensionChecker(threshold=threshold)
    # 10 deltas of +5.0 each → score = +50.0 >> -100.0 floor
    store = _store_with_deltas(count=10, delta_value=5.0)
    decision = checker.check("agent-a", store)
    assert not decision.suspended
    assert decision.reason == "score_above_floor"
    assert decision.score is not None and decision.score > threshold.score_floor


def test_score_exactly_at_floor_not_suspended(monkeypatch):
    monkeypatch.setenv(_FLAG, "1")
    # score >= floor → not suspended (boundary is inclusive on the floor).
    threshold = SuspensionThreshold(score_floor=-50.0, min_samples=5)
    checker = SuspensionChecker(threshold=threshold)
    store = ReputationStore()
    for i in range(5):
        store.record_delta(_delta("agent-b", delta=-10.0, idx=i))
    # score = -50.0 exactly = floor → not suspended
    decision = checker.check("agent-b", store)
    assert not decision.suspended
    assert decision.reason == "score_above_floor"


# ---------------------------------------------------------------------------
# score_below_floor (suspension fires)
# ---------------------------------------------------------------------------


def test_score_below_floor_suspended(monkeypatch):
    monkeypatch.setenv(_FLAG, "1")
    threshold = SuspensionThreshold(score_floor=-50.0, min_samples=5)
    checker = SuspensionChecker(threshold=threshold)
    # 10 deltas of -10.0 → score = -100.0 < -50.0
    store = _store_with_deltas(count=10, delta_value=-10.0)
    decision = checker.check("agent-a", store)
    assert decision.suspended
    assert decision.reason == "score_below_floor"
    assert decision.score is not None and decision.score < threshold.score_floor
    assert decision.sample_count == 10


def test_suspension_carries_advisory_days(monkeypatch):
    monkeypatch.setenv(_FLAG, "1")
    threshold = SuspensionThreshold(score_floor=-1.0, min_samples=1, suspension_days=14.0)
    checker = SuspensionChecker(threshold=threshold)
    store = ReputationStore()
    store.record_delta(_delta("agent-c", delta=-5.0, idx=0))
    decision = checker.check("agent-c", store)
    assert decision.suspended
    assert decision.suspension_days == 14.0


# ---------------------------------------------------------------------------
# Domain filtering
# ---------------------------------------------------------------------------


def test_domain_filter_counts_only_matching(monkeypatch):
    monkeypatch.setenv(_FLAG, "1")
    threshold = SuspensionThreshold(
        score_floor=-50.0,
        min_samples=5,
        domains=frozenset({"prediction_market"}),
    )
    checker = SuspensionChecker(threshold=threshold)
    store = ReputationStore()
    # 8 deltas in prediction_market (score = -80), 5 in code_pr (score = +50)
    for i in range(8):
        store.record_delta(_delta("agent-d", delta=-10.0, domain="prediction_market", idx=i))
    for i in range(5):
        store.record_delta(_delta("agent-d", delta=10.0, domain="code_pr", idx=i + 100))
    decision = checker.check("agent-d", store)
    assert decision.suspended
    assert decision.reason == "score_below_floor"
    assert decision.sample_count == 8


def test_domain_filter_insufficient_samples(monkeypatch):
    monkeypatch.setenv(_FLAG, "1")
    threshold = SuspensionThreshold(
        score_floor=-1.0,
        min_samples=5,
        domains=frozenset({"prediction_market"}),
    )
    checker = SuspensionChecker(threshold=threshold)
    store = ReputationStore()
    # Only 3 prediction_market deltas: below min_samples
    for i in range(3):
        store.record_delta(_delta("agent-e", delta=-100.0, domain="prediction_market", idx=i))
    decision = checker.check("agent-e", store)
    assert not decision.suspended
    assert decision.reason == "insufficient_samples"


# ---------------------------------------------------------------------------
# threshold_fingerprint in decisions
# ---------------------------------------------------------------------------


def test_decision_threshold_fingerprint_matches(monkeypatch):
    monkeypatch.setenv(_FLAG, "1")
    threshold = SuspensionThreshold(score_floor=-200.0, min_samples=3)
    checker = SuspensionChecker(threshold=threshold)
    store = _store_with_deltas(count=5, delta_value=1.0)
    decision = checker.check("agent-a", store)
    assert decision.threshold_fingerprint == threshold.fingerprint()
