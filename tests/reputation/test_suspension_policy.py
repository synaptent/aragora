"""Tests for aragora.reputation.suspension_policy (AGT-05 #6066 sub-6).

All tests run without network access. The feature flag is toggled via
monkeypatch so the global environment is never mutated between tests.
"""

from __future__ import annotations

import json
import math
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


@pytest.fixture(autouse=True, scope="module")
def _flag_not_leaked_by_module():
    # Module scope: the repo conftest's autouse fixtures request monkeypatch
    # first, so a function-scoped check would run before monkeypatch's undo.
    # Module teardown sees what the next test module in the worker inherits.
    before = os.environ.get(_FLAG)
    yield
    assert os.environ.get(_FLAG) == before, f"{_FLAG} leaked out of this module"


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
    # setenv records the original value, so teardown restores it even though
    # enable_suspension() writes os.environ directly.
    monkeypatch.setenv(_FLAG, "0")
    assert not suspension_enabled()
    enable_suspension()
    assert suspension_enabled()


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


def test_threshold_rejects_nan_suspension_days():
    with pytest.raises(ValueError, match="suspension_days must be > 0"):
        SuspensionThreshold(suspension_days=float("nan"))


def test_threshold_rejects_nan_score_floor():
    # Every comparison with NaN is False, so a NaN floor would suspend any
    # agent with enough samples regardless of score.
    with pytest.raises(ValueError, match="score_floor must be a finite number"):
        SuspensionThreshold(score_floor=float("nan"))


@pytest.mark.parametrize("floor", [math.inf, -math.inf])
def test_threshold_rejects_infinite_score_floor(floor):
    # +inf suspends every agent with enough samples; -inf never suspends.
    with pytest.raises(ValueError, match="score_floor must be a finite number"):
        SuspensionThreshold(score_floor=floor)


def test_threshold_rejects_infinite_suspension_days():
    with pytest.raises(ValueError, match="suspension_days must be > 0 and finite"):
        SuspensionThreshold(suspension_days=math.inf)


@pytest.mark.parametrize("value", [float("nan"), 2.5, True])
def test_threshold_rejects_non_integer_min_samples(value):
    # ``sample_count < nan`` is always False, so a NaN minimum would let
    # suspension fire on a single sample.
    with pytest.raises(ValueError, match="min_samples must be an integer"):
        SuspensionThreshold(min_samples=value)


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


@pytest.mark.parametrize("domains", [None, frozenset({"prediction_market"})])
def test_non_finite_score_is_not_suspended(monkeypatch, tmp_path, domains):
    # json.loads accepts a NaN literal, so one damaged ledger line makes the
    # score NaN; NaN >= floor is False and must not read as below the floor.
    monkeypatch.setenv(_FLAG, "1")
    path = tmp_path / "deltas.jsonl"
    store = ReputationStore(path=path)
    for i in range(12):
        store.record_delta(_delta("agent-n", delta=5.0, idx=i))
    lines = path.read_text(encoding="utf-8").splitlines()
    damaged = json.loads(lines[0])
    damaged["delta"] = float("nan")
    lines[0] = json.dumps(damaged, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    checker = SuspensionChecker(threshold=SuspensionThreshold(domains=domains))
    decision = checker.check("agent-n", ReputationStore.load_from_file(path))
    assert not decision.suspended
    assert decision.reason == "non_finite_score"
    assert decision.score is None
    assert decision.sample_count == 12


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
# Reversed deltas (ReputationStore.reverse_delta)
# ---------------------------------------------------------------------------


def test_reversed_deltas_do_not_count_toward_min_samples(monkeypatch):
    monkeypatch.setenv(_FLAG, "1")
    checker = SuspensionChecker()  # default: floor -50, min_samples 10
    store = ReputationStore()
    for i in range(11):
        d = _delta("agent-r", delta=10.0, idx=i)
        store.record_delta(d)
        store.reverse_delta(d.delta_id)
    store.record_delta(_delta("agent-r", delta=-60.0, idx=99))
    decision = checker.check("agent-r", store)
    assert not decision.suspended
    assert decision.reason == "insufficient_samples"
    assert decision.sample_count == 1
    assert decision.score == -60.0


def test_domain_filter_excludes_reversed_deltas(monkeypatch, tmp_path):
    monkeypatch.setenv(_FLAG, "1")
    threshold = SuspensionThreshold(
        score_floor=-50.0,
        min_samples=3,
        domains=frozenset({"prediction_market"}),
    )
    checker = SuspensionChecker(threshold=threshold)
    path = tmp_path / "deltas.jsonl"
    store = ReputationStore(path=path)
    for i in range(12):
        store.record_delta(_delta("agent-s", delta=-10.0, idx=i))
    for i in range(8):
        store.reverse_delta(f"rep_agent-s_prediction_market_{i:04d}")
    assert store.get_score("agent-s") == -40.0
    for s in (store, ReputationStore.load_from_file(path)):
        decision = checker.check("agent-s", s)
        assert not decision.suspended
        assert decision.reason == "score_above_floor"
        assert decision.score == -40.0
        assert decision.sample_count == 4


@pytest.mark.parametrize("domains", [None, frozenset({"prediction_market"})])
def test_fully_reversed_history_is_no_data(monkeypatch, domains):
    monkeypatch.setenv(_FLAG, "1")
    checker = SuspensionChecker(threshold=SuspensionThreshold(domains=domains))
    store = _store_with_deltas("agent-t", count=12, delta_value=-10.0)
    for i in range(12):
        store.reverse_delta(f"rep_agent-t_prediction_market_{i:04d}")
    decision = checker.check("agent-t", store)
    assert not decision.suspended
    assert decision.reason == "no_data"
    assert decision.score is None
    assert decision.sample_count == 0


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


# ---------------------------------------------------------------------------
# Domain-filtered path applies time-decay (same footing as all-domain path)
# ---------------------------------------------------------------------------


def _decaying_delta(
    agent_id: str,
    *,
    delta: float,
    domain: str,
    idx: int,
    applied_at: str,
    half_life_days: float,
) -> ReputationDelta:
    return ReputationDelta(
        delta_id=f"rep_{agent_id}_{domain}_decay_{idx:04d}",
        agent_id=agent_id,
        domain=domain,
        claim_id=f"claim-{idx}",
        resolution_id=f"res-{idx}",
        delta=delta,
        scoring_rule="binary",
        applied_at=applied_at,
        decay_half_life_days=half_life_days,
        reason={"idx": idx},
    )


def test_domain_filter_applies_decay(monkeypatch):
    """Old losses in the filtered domain decay instead of being summed raw.

    Six deltas of -10 recorded many half-lives ago would sum to -60 (below a
    -50 floor) if the domain path ignored decay; decayed they are ~0, so the
    agent must stay eligible.
    """
    monkeypatch.setenv(_FLAG, "1")
    threshold = SuspensionThreshold(
        score_floor=-50.0,
        min_samples=5,
        domains=frozenset({"prediction_market"}),
    )
    store = ReputationStore()
    ancient = "2020-01-01T00:00:00Z"
    for i in range(6):
        store.record_delta(
            _decaying_delta(
                "agent-e",
                delta=-10.0,
                domain="prediction_market",
                idx=i,
                applied_at=ancient,
                half_life_days=7.0,
            )
        )
    decision = SuspensionChecker(threshold=threshold).check("agent-e", store)
    assert not decision.suspended
    assert decision.reason == "score_above_floor"
    assert decision.sample_count == 6
    assert decision.score is not None
    assert decision.score == pytest.approx(0.0, abs=1e-6)
    # The raw (undecayed) slice really is below the floor, proving decay was applied.
    assert store.domain_score("agent-e", "prediction_market", apply_decay=False) == pytest.approx(
        -60.0
    )


def test_domain_filter_matches_store_domain_score(monkeypatch):
    monkeypatch.setenv(_FLAG, "1")
    threshold = SuspensionThreshold(
        score_floor=-1000.0,
        min_samples=1,
        domains=frozenset({"prediction_market", "code_pr"}),
    )
    store = ReputationStore()
    for i in range(4):
        store.record_delta(_delta("agent-f", delta=-10.0, domain="prediction_market", idx=i))
    for i in range(3):
        store.record_delta(_delta("agent-f", delta=5.0, domain="code_pr", idx=i + 50))
    store.record_delta(_delta("agent-f", delta=-999.0, domain="debate_position", idx=99))
    decision = SuspensionChecker(threshold=threshold).check("agent-f", store)
    assert decision.sample_count == 7
    assert decision.score == pytest.approx(
        store.domain_score("agent-f", threshold.domains, apply_decay=True)
    )
    assert decision.score == pytest.approx(-25.0)
