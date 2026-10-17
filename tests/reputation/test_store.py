"""Tests for aragora.reputation.store (AGT-05 ReputationStore)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from aragora.reputation.settlement import settle_claim
from aragora.reputation.store import (
    AgentScore,
    ReputationStore,
    ReputationStoreError,
    enable_store,
    store_enabled,
)
from aragora.reputation.types import (
    DOMAIN_DEBATE_POSITION,
    DOMAIN_PREDICTION_MARKET,
    ReputationDelta,
    ReputationDeltaReversed,
    ResolvedClaim,
    StakeableClaim,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _claim(
    *,
    agent_id: str = "alice",
    probability: float | None = 0.8,
    position: str = "yes",
    stake: int = 100,
    domain: str = DOMAIN_PREDICTION_MARKET,
    resolution_id: str = "mkt_abc",
) -> StakeableClaim:
    return StakeableClaim.create(
        agent_id=agent_id,
        domain=domain,
        statement="PR #42 will be merged within 30 days",
        position=position,
        stake_units=stake,
        resolution_source="synthetic_github",
        resolution_id=resolution_id,
        predicted_probability=probability,
    )


def _resolved(claim: StakeableClaim, outcome: str = "yes") -> ResolvedClaim:
    return ResolvedClaim(
        claim_id=claim.claim_id,
        outcome=outcome,  # type: ignore[arg-type]
        resolved_at="2026-04-24T12:00:00Z",
        resolution_source="synthetic_github",
    )


def _delta(
    *,
    agent_id: str = "alice",
    delta: float = 50.0,
    domain: str = DOMAIN_PREDICTION_MARKET,
    decay_half_life_days: float | None = None,
    applied_at: str | None = None,
    resolution_id: str = "mkt_abc",
) -> ReputationDelta:
    claim = _claim(agent_id=agent_id, domain=domain, resolution_id=resolution_id)
    resolved = _resolved(claim, "yes")
    d = settle_claim(claim, resolved, decay_half_life_days=decay_half_life_days)
    # Return a patched version with the desired delta value for determinism.
    return ReputationDelta(
        delta_id=d.delta_id,
        agent_id=agent_id,
        domain=domain,
        claim_id=d.claim_id,
        resolution_id=d.resolution_id,
        delta=delta,
        scoring_rule=d.scoring_rule,
        applied_at=applied_at or d.applied_at,
        decay_half_life_days=decay_half_life_days,
        reason=d.reason,
    )


# ---------------------------------------------------------------------------
# Flag helpers
# ---------------------------------------------------------------------------


class TestFlagHelpers:
    def test_store_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARAGORA_REPUTATION_FLOW_ENABLED", raising=False)
        assert store_enabled() is False

    def test_enable_store_sets_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARAGORA_REPUTATION_FLOW_ENABLED", raising=False)
        enable_store()
        assert store_enabled() is True

    def test_store_enabled_via_env_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_REPUTATION_FLOW_ENABLED", "1")
        assert store_enabled() is True

    def test_store_enabled_via_true_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_REPUTATION_FLOW_ENABLED", "true")
        assert store_enabled() is True


# ---------------------------------------------------------------------------
# record_delta and basic queries
# ---------------------------------------------------------------------------


class TestRecordAndQuery:
    def test_empty_store_len_zero(self) -> None:
        store = ReputationStore()
        assert len(store) == 0

    def test_empty_agent_score_zero(self) -> None:
        store = ReputationStore()
        assert store.get_score("ghost") == 0.0

    def test_record_single_delta(self) -> None:
        store = ReputationStore()
        d = _delta(delta=60.0)
        store.record_delta(d)
        assert len(store) == 1
        assert store.get_score("alice") == pytest.approx(60.0)

    def test_record_multiple_deltas_accumulate(self) -> None:
        store = ReputationStore()
        store.record_delta(_delta(agent_id="alice", delta=40.0, resolution_id="r1"))
        store.record_delta(_delta(agent_id="alice", delta=-20.0, resolution_id="r2"))
        assert len(store) == 2
        assert store.get_score("alice") == pytest.approx(20.0)

    def test_multiple_agents_isolated(self) -> None:
        store = ReputationStore()
        store.record_delta(_delta(agent_id="alice", delta=80.0))
        store.record_delta(_delta(agent_id="bob", delta=30.0))
        assert store.get_score("alice") == pytest.approx(80.0)
        assert store.get_score("bob") == pytest.approx(30.0)

    def test_agent_ids_sorted(self) -> None:
        store = ReputationStore()
        store.record_delta(_delta(agent_id="charlie", delta=10.0))
        store.record_delta(_delta(agent_id="alice", delta=10.0))
        store.record_delta(_delta(agent_id="bob", delta=10.0))
        assert store.agent_ids() == ["alice", "bob", "charlie"]

    def test_deltas_for_returns_copy(self) -> None:
        store = ReputationStore()
        d = _delta(delta=50.0)
        store.record_delta(d)
        history = store.deltas_for("alice")
        assert len(history) == 1
        history.clear()  # mutating the copy must not affect the store
        assert len(store.deltas_for("alice")) == 1

    def test_empty_agent_rejects(self) -> None:
        store = ReputationStore()
        d = _delta()
        # Craft a delta with empty agent_id by bypassing the factory
        bad = ReputationDelta(
            delta_id=d.delta_id,
            agent_id="  ",  # whitespace only
            domain=d.domain,
            claim_id=d.claim_id,
            resolution_id=d.resolution_id,
            delta=d.delta,
            scoring_rule=d.scoring_rule,
            applied_at=d.applied_at,
            decay_half_life_days=d.decay_half_life_days,
            reason=d.reason,
        )
        with pytest.raises(ReputationStoreError, match="agent_id"):
            store.record_delta(bad)


# ---------------------------------------------------------------------------
# AgentScore
# ---------------------------------------------------------------------------


class TestAgentScore:
    def test_agent_score_structure(self) -> None:
        store = ReputationStore()
        store.record_delta(_delta(agent_id="alice", delta=30.0, domain=DOMAIN_PREDICTION_MARKET))
        store.record_delta(_delta(agent_id="alice", delta=10.0, domain=DOMAIN_DEBATE_POSITION))
        score = store.agent_score("alice", apply_decay=False)
        assert score.agent_id == "alice"
        assert score.delta_count == 2
        assert score.running_score == pytest.approx(40.0)
        assert sorted(score.domains) == [DOMAIN_DEBATE_POSITION, DOMAIN_PREDICTION_MARKET]

    def test_all_scores_sorted_descending(self) -> None:
        store = ReputationStore()
        store.record_delta(_delta(agent_id="charlie", delta=10.0))
        store.record_delta(_delta(agent_id="alice", delta=80.0))
        store.record_delta(_delta(agent_id="bob", delta=40.0))
        scores = store.all_scores(apply_decay=False)
        assert [s.agent_id for s in scores] == ["alice", "bob", "charlie"]
        assert scores[0].running_score == pytest.approx(80.0)

    def test_agent_score_to_json(self) -> None:
        score = AgentScore(
            agent_id="alice",
            running_score=42.5,
            delta_count=3,
            domains=["prediction_market"],
        )
        j = score.to_json()
        assert j["agent_id"] == "alice"
        assert j["running_score"] == pytest.approx(42.5)
        assert j["delta_count"] == 3
        assert j["domains"] == ["prediction_market"]


# ---------------------------------------------------------------------------
# Decay
# ---------------------------------------------------------------------------


class TestDecay:
    def test_no_decay_when_half_life_none(self) -> None:
        store = ReputationStore()
        d = _delta(delta=100.0, decay_half_life_days=None)
        store.record_delta(d)
        assert store.get_score("alice", apply_decay=True) == pytest.approx(100.0)

    def test_apply_decay_false_returns_raw_sum(self) -> None:
        store = ReputationStore()
        store.record_delta(_delta(delta=100.0, decay_half_life_days=30.0))
        # Raw sum ignores decay
        assert store.get_score("alice", apply_decay=False) == pytest.approx(100.0)

    def test_fresh_delta_barely_decays(self) -> None:
        store = ReputationStore()
        now_iso = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
        d = _delta(delta=100.0, decay_half_life_days=30.0, applied_at=now_iso)
        store.record_delta(d)
        score = store.get_score("alice", apply_decay=True)
        # Should be very close to 100 since it was just applied
        assert score == pytest.approx(100.0, rel=0.01)

    def test_one_half_life_old_delta_halves(self) -> None:
        store = ReputationStore()
        thirty_days_ago = (
            (datetime.now(tz=UTC) - timedelta(days=30)).isoformat().replace("+00:00", "Z")
        )
        d = _delta(delta=100.0, decay_half_life_days=30.0, applied_at=thirty_days_ago)
        store.record_delta(d)
        score = store.get_score("alice", apply_decay=True)
        assert score == pytest.approx(50.0, rel=0.02)

    def test_very_old_delta_decays_near_zero(self) -> None:
        store = ReputationStore()
        old = (datetime.now(tz=UTC) - timedelta(days=365)).isoformat().replace("+00:00", "Z")
        d = _delta(delta=100.0, decay_half_life_days=30.0, applied_at=old)
        store.record_delta(d)
        score = store.get_score("alice", apply_decay=True)
        assert score < 1.0  # ~100 * 2^(-365/30) ≈ 0.00032


# ---------------------------------------------------------------------------
# Persistence (JSONL round-trip)
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_file_created_on_record(self, tmp_path: Path) -> None:
        ledger = tmp_path / "rep.jsonl"
        store = ReputationStore(path=ledger)
        store.record_delta(_delta(delta=50.0))
        assert ledger.exists()

    def test_file_has_one_line_per_delta(self, tmp_path: Path) -> None:
        ledger = tmp_path / "rep.jsonl"
        store = ReputationStore(path=ledger)
        store.record_delta(_delta(delta=50.0, resolution_id="r1"))
        store.record_delta(_delta(delta=30.0, resolution_id="r2"))
        lines = [l for l in ledger.read_text().splitlines() if l.strip()]
        assert len(lines) == 2

    def test_load_from_file_round_trip(self, tmp_path: Path) -> None:
        ledger = tmp_path / "rep.jsonl"
        store = ReputationStore(path=ledger)
        store.record_delta(_delta(agent_id="alice", delta=70.0))
        store.record_delta(_delta(agent_id="bob", delta=20.0))

        reloaded = ReputationStore.load_from_file(ledger)
        assert reloaded.get_score("alice", apply_decay=False) == pytest.approx(70.0)
        assert reloaded.get_score("bob", apply_decay=False) == pytest.approx(20.0)

    def test_load_from_missing_file_returns_empty(self, tmp_path: Path) -> None:
        store = ReputationStore.load_from_file(tmp_path / "ghost.jsonl")
        assert len(store) == 0

    def test_load_skips_corrupt_lines(self, tmp_path: Path) -> None:
        ledger = tmp_path / "rep.jsonl"
        # Write one valid line and one invalid line
        good = _delta(delta=55.0)
        with ledger.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(good.to_json(), sort_keys=True) + "\n")
            fh.write("not valid json\n")
        store = ReputationStore.load_from_file(ledger)
        assert len(store) == 1
        assert store.get_score("alice", apply_decay=False) == pytest.approx(55.0)

    def test_no_path_no_file_written(self, tmp_path: Path) -> None:
        store = ReputationStore(path=None)
        store.record_delta(_delta(delta=10.0))
        assert not any(tmp_path.iterdir())

    def test_write_failure_raises_without_mutating_memory(self, tmp_path: Path) -> None:
        ledger = tmp_path / "rep.jsonl"
        store = ReputationStore(path=ledger)
        with patch.object(Path, "open", side_effect=OSError("disk full")):
            with pytest.raises(ReputationStoreError, match="could not persist"):
                store.record_delta(_delta(delta=10.0))
        assert len(store) == 0
        assert store.get_score("alice", apply_decay=False) == 0.0


# ---------------------------------------------------------------------------
# AGT-05 sub-deliverable #7: ReputationDeltaReversed + reverse_delta()
# ---------------------------------------------------------------------------


class TestDeltaReversal:
    def test_reverse_removes_delta_from_score(self) -> None:
        store = ReputationStore()
        d = _delta(delta=50.0)
        store.record_delta(d)
        assert store.get_score("alice", apply_decay=False) == pytest.approx(50.0)

        store.reverse_delta(d.delta_id)

        assert store.get_score("alice", apply_decay=False) == pytest.approx(0.0)

    def test_reverse_unknown_delta_id_raises_key_error(self) -> None:
        store = ReputationStore()
        with pytest.raises(KeyError, match="not found"):
            store.reverse_delta("does_not_exist")

    def test_reverse_already_reversed_is_idempotent(self) -> None:
        store = ReputationStore()
        d = _delta(delta=10.0)
        store.record_delta(d)
        first = store.reverse_delta(d.delta_id, reason={"cause": "first"})

        second = store.reverse_delta(d.delta_id, reason={"cause": "second"})

        assert second == first
        assert len(store.reversals_for("alice")) == 1
        assert store.get_score("alice", apply_decay=False) == pytest.approx(0.0)

    def test_reverse_returns_correct_reversal_event(self) -> None:
        store = ReputationStore()
        d = _delta(delta=30.0)
        store.record_delta(d)

        reversal = store.reverse_delta(d.delta_id, reason={"cause": "reopened_resolution"})

        assert isinstance(reversal, ReputationDeltaReversed)
        assert reversal.original_delta_id == d.delta_id
        assert reversal.agent_id == d.agent_id
        assert reversal.domain == d.domain
        assert reversal.counter_delta == pytest.approx(-30.0)
        assert reversal.reason == {"cause": "reopened_resolution"}
        assert reversal.reversal_id.startswith("rev_")

    def test_reverse_partial_cancels_only_that_delta(self) -> None:
        store = ReputationStore()
        d1 = _delta(delta=40.0, agent_id="alice", resolution_id="r1")
        d2 = _delta(delta=20.0, agent_id="alice", resolution_id="r2")
        store.record_delta(d1)
        store.record_delta(d2)
        assert store.get_score("alice", apply_decay=False) == pytest.approx(60.0)

        store.reverse_delta(d1.delta_id)

        assert store.get_score("alice", apply_decay=False) == pytest.approx(20.0)

    def test_reverse_does_not_affect_other_agents(self) -> None:
        store = ReputationStore()
        da = _delta(delta=50.0, agent_id="alice", resolution_id="r1")
        db = _delta(delta=70.0, agent_id="bob", resolution_id="r2")
        store.record_delta(da)
        store.record_delta(db)

        store.reverse_delta(da.delta_id)

        assert store.get_score("alice", apply_decay=False) == pytest.approx(0.0)
        assert store.get_score("bob", apply_decay=False) == pytest.approx(70.0)

    def test_reversals_for_returns_all_reversals_for_agent(self) -> None:
        store = ReputationStore()
        d1 = _delta(delta=10.0, agent_id="alice", resolution_id="r1")
        d2 = _delta(delta=20.0, agent_id="alice", resolution_id="r2")
        d3 = _delta(delta=30.0, agent_id="bob", resolution_id="r3")
        store.record_delta(d1)
        store.record_delta(d2)
        store.record_delta(d3)

        store.reverse_delta(d1.delta_id)
        store.reverse_delta(d3.delta_id)

        alice_reversals = store.reversals_for("alice")
        assert len(alice_reversals) == 1
        assert alice_reversals[0].original_delta_id == d1.delta_id

        bob_reversals = store.reversals_for("bob")
        assert len(bob_reversals) == 1
        assert bob_reversals[0].original_delta_id == d3.delta_id

    def test_reversal_to_json_round_trip(self) -> None:
        store = ReputationStore()
        d = _delta(delta=-15.0)
        store.record_delta(d)
        reversal = store.reverse_delta(d.delta_id, reason={"source": "dispute"})

        payload = reversal.to_json()
        rebuilt = ReputationDeltaReversed.from_json(payload)

        assert rebuilt.reversal_id == reversal.reversal_id
        assert rebuilt.original_delta_id == reversal.original_delta_id
        assert rebuilt.counter_delta == pytest.approx(reversal.counter_delta)
        assert rebuilt.reason == {"source": "dispute"}

    def test_len_unchanged_after_reversal(self) -> None:
        store = ReputationStore()
        d = _delta(delta=10.0)
        store.record_delta(d)
        store.reverse_delta(d.delta_id)
        assert len(store) == 1

    def test_reversal_survives_reload(self, tmp_path: Path) -> None:
        """Reversed delta must stay excluded after load_from_file (durability)."""
        ledger = tmp_path / "rep.jsonl"
        store = ReputationStore(path=ledger)
        d = _delta(delta=75.0)
        store.record_delta(d)
        assert store.get_score("alice", apply_decay=False) == pytest.approx(75.0)

        store.reverse_delta(d.delta_id, reason={"cause": "resolution_reopened"})
        assert store.get_score("alice", apply_decay=False) == pytest.approx(0.0)

        # Reload from disk — the reversal file must be present and loaded
        reloaded = ReputationStore.load_from_file(ledger)
        assert reloaded.get_score("alice", apply_decay=False) == pytest.approx(0.0)
        assert len(reloaded.reversals_for("alice")) == 1
        assert reloaded.reversals_for("alice")[0].original_delta_id == d.delta_id

    def test_reversal_after_reload_survives_second_reload(self, tmp_path: Path) -> None:
        """Persist reverse_delta() called after reconstructing from an existing ledger."""
        ledger = tmp_path / "rep.jsonl"
        store = ReputationStore(path=ledger)
        d = _delta(delta=75.0)
        store.record_delta(d)

        reloaded = ReputationStore.load_from_file(ledger)
        assert reloaded.get_score("alice", apply_decay=False) == pytest.approx(75.0)

        reloaded.reverse_delta(d.delta_id, reason={"cause": "resolution_reopened"})

        reloaded_again = ReputationStore.load_from_file(ledger)
        assert reloaded_again.get_score("alice", apply_decay=False) == pytest.approx(0.0)
        assert len(reloaded_again.reversals_for("alice")) == 1
        assert reloaded_again.reversals_for("alice")[0].original_delta_id == d.delta_id

    def test_persisted_reversal_is_idempotent_after_reload(self, tmp_path: Path) -> None:
        ledger = tmp_path / "rep.jsonl"
        store = ReputationStore(path=ledger)
        d = _delta(delta=25.0)
        store.record_delta(d)
        first = store.reverse_delta(d.delta_id, reason={"cause": "first"})

        reloaded = ReputationStore.load_from_file(ledger)
        second = reloaded.reverse_delta(d.delta_id, reason={"cause": "second"})

        assert second == first
        assert reloaded.get_score("alice", apply_decay=False) == pytest.approx(0.0)
        reversal_lines = [
            line
            for line in (tmp_path / "rep.reversals.jsonl").read_text().splitlines()
            if line.strip()
        ]
        assert len(reversal_lines) == 1


# ---------------------------------------------------------------------------
# Per-domain slices (AGT-05: no single aggregate score for dispatch)
# ---------------------------------------------------------------------------


class TestDomainScores:
    def _two_domain_store(self) -> ReputationStore:
        store = ReputationStore()
        store.record_delta(_delta(delta=30.0, domain=DOMAIN_PREDICTION_MARKET, resolution_id="m1"))
        store.record_delta(_delta(delta=-10.0, domain=DOMAIN_PREDICTION_MARKET, resolution_id="m2"))
        store.record_delta(_delta(delta=15.0, domain=DOMAIN_DEBATE_POSITION, resolution_id="d1"))
        return store

    def test_single_domain_string(self) -> None:
        store = self._two_domain_store()
        pm = store.domain_score("alice", DOMAIN_PREDICTION_MARKET, apply_decay=False)
        assert pm == pytest.approx(20.0)
        dp = store.domain_score("alice", DOMAIN_DEBATE_POSITION, apply_decay=False)
        assert dp == pytest.approx(15.0)

    def test_iterable_of_domains_sums_matching(self) -> None:
        store = self._two_domain_store()
        both = store.domain_score(
            "alice",
            frozenset({DOMAIN_PREDICTION_MARKET, DOMAIN_DEBATE_POSITION}),
            apply_decay=False,
        )
        assert both == pytest.approx(store.get_score("alice", apply_decay=False))

    def test_unknown_domain_or_agent_returns_zero(self) -> None:
        store = self._two_domain_store()
        assert store.domain_score("alice", "code_pr") == 0.0
        assert store.domain_score("nobody", DOMAIN_PREDICTION_MARKET) == 0.0
        assert store.domain_scores("nobody") == {}

    def test_domain_scores_maps_each_domain(self) -> None:
        store = self._two_domain_store()
        scores = store.domain_scores("alice", apply_decay=False)
        assert list(scores) == sorted([DOMAIN_DEBATE_POSITION, DOMAIN_PREDICTION_MARKET])
        assert scores[DOMAIN_PREDICTION_MARKET] == pytest.approx(20.0)
        assert scores[DOMAIN_DEBATE_POSITION] == pytest.approx(15.0)

    def test_reversed_delta_excluded_from_domain_slice(self) -> None:
        store = self._two_domain_store()
        target = next(d for d in store.deltas_for("alice") if d.delta == pytest.approx(15.0))
        store.reverse_delta(target.delta_id)
        assert store.domain_score("alice", DOMAIN_DEBATE_POSITION, apply_decay=False) == 0.0
        # A domain whose only deltas were reversed drops out of the map entirely.
        assert DOMAIN_DEBATE_POSITION not in store.domain_scores("alice")
        assert store.domain_scores("alice", apply_decay=False)[
            DOMAIN_PREDICTION_MARKET
        ] == pytest.approx(20.0)

    def test_domain_score_applies_decay_with_explicit_clock(self) -> None:
        now = datetime(2026, 10, 1, tzinfo=UTC)
        thirty_days_ago = (now - timedelta(days=30)).isoformat().replace("+00:00", "Z")
        store = ReputationStore()
        store.record_delta(
            _delta(
                delta=100.0,
                domain=DOMAIN_PREDICTION_MARKET,
                decay_half_life_days=30.0,
                applied_at=thirty_days_ago,
                resolution_id="old",
            )
        )
        store.record_delta(
            _delta(
                delta=100.0,
                domain=DOMAIN_DEBATE_POSITION,
                decay_half_life_days=None,
                applied_at=thirty_days_ago,
                resolution_id="nodecay",
            )
        )
        # One half-life elapsed: the decaying slice is worth exactly half.
        assert store.domain_score("alice", DOMAIN_PREDICTION_MARKET, now=now) == pytest.approx(50.0)
        # The non-decaying slice is unaffected by the clock.
        assert store.domain_score("alice", DOMAIN_DEBATE_POSITION, now=now) == pytest.approx(100.0)
        # Raw sums still available per domain.
        assert store.domain_score(
            "alice", DOMAIN_PREDICTION_MARKET, apply_decay=False, now=now
        ) == pytest.approx(100.0)
        by_domain = store.domain_scores("alice", now=now)
        assert by_domain[DOMAIN_PREDICTION_MARKET] == pytest.approx(50.0)
        assert by_domain[DOMAIN_DEBATE_POSITION] == pytest.approx(100.0)

    def test_domain_slices_sum_to_aggregate(self) -> None:
        now = datetime(2026, 10, 1, tzinfo=UTC)
        ten_days_ago = (now - timedelta(days=10)).isoformat().replace("+00:00", "Z")
        store = ReputationStore()
        for i, domain in enumerate([DOMAIN_PREDICTION_MARKET, DOMAIN_DEBATE_POSITION, "code_pr"]):
            store.record_delta(
                _delta(
                    delta=40.0 - 10.0 * i,
                    domain=domain,
                    decay_half_life_days=20.0,
                    applied_at=ten_days_ago,
                    resolution_id=f"r{i}",
                )
            )
        total = sum(store.domain_scores("alice", now=now).values())
        all_domains = store.domain_score("alice", store.domain_scores("alice"), now=now)
        assert total == pytest.approx(all_domains)
