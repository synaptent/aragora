"""Tests for DIC-17 follow-up proposal bridge."""

from __future__ import annotations

import pytest

from aragora.epistemic.followup import (
    DEFAULT_CRUX_LOAD_BEARING_THRESHOLD,
    DEFAULT_DELTA_LOSS_THRESHOLD,
    FollowupProposal,
    propose_followup_for_crux,
    propose_followup_for_cruxset,
    propose_followup_for_failed_claim,
)
from aragora.reasoning.cruxset import Crux, CruxPosition, CruxSet
from aragora.reputation.settlement import settle_claim
from aragora.reputation.types import (
    DOMAIN_PREDICTION_MARKET,
    ResolvedClaim,
    StakeableClaim,
)


def _make_crux(*, score: float = 0.85, crux_id: str = "c1") -> Crux:
    return Crux(
        crux_id=crux_id,
        statement="X is load-bearing",
        positions=(
            CruxPosition(side="for", agents=("alice",)),
            CruxPosition(side="against", agents=("bob",)),
        ),
        load_bearing_score=score,
        evidence_gaps=("no benchmark for X",),
        counterfactual="if X is false, decision flips",
        candidate_verifier="docs/spec.md",
    )


def _make_failed_settlement(
    *,
    probability: float = 0.95,
    stake: int = 50,
    outcome: str = "no",
) -> tuple[StakeableClaim, ResolvedClaim, object]:
    claim = StakeableClaim.create(
        agent_id="alice",
        domain=DOMAIN_PREDICTION_MARKET,
        statement="will PR #1 merge",
        position="yes",
        stake_units=stake,
        resolution_source="synthetic_github",
        resolution_id="mkt_x",
        predicted_probability=probability,
    )
    resolved = ResolvedClaim(
        claim_id=claim.claim_id,
        outcome=outcome,  # type: ignore[arg-type]
        resolved_at="2026-04-24T12:00:00Z",
        resolution_source="synthetic_github",
    )
    delta = settle_claim(claim, resolved, scoring_rule="brier_proper")
    return claim, resolved, delta


class TestFollowupProposalValidation:
    def test_rejects_unknown_source_kind(self) -> None:
        with pytest.raises(ValueError):
            FollowupProposal(
                source_kind="something",
                source_key="k",
                title="t",
                body="b",
                labels=(),
                rationale="r",
            )

    def test_rejects_empty_source_key_or_title_or_body(self) -> None:
        for field in ("source_key", "title", "body"):
            kwargs = dict(
                source_kind="crux",
                source_key="k",
                title="t",
                body="b",
                labels=(),
                rationale="r",
            )
            kwargs[field] = " "
            with pytest.raises(ValueError):
                FollowupProposal(**kwargs)  # type: ignore[arg-type]

    def test_rejects_boss_ready_label(self) -> None:
        with pytest.raises(ValueError):
            FollowupProposal(
                source_kind="crux",
                source_key="k",
                title="t",
                body="b",
                labels=("epistemic", "boss-ready"),
                rationale="r",
            )

    def test_to_gh_create_args_shape(self) -> None:
        proposal = FollowupProposal(
            source_kind="crux",
            source_key="k",
            title="t",
            body="b",
            labels=("epistemic", "crux"),
            rationale="r",
        )
        args = proposal.to_gh_create_args(repo="owner/repo")
        assert args[:2] == ["issue", "create"]
        assert "--repo" in args
        assert "owner/repo" in args
        assert "--title" in args and "t" in args
        assert args.count("--label") == 2
        assert "boss-ready" not in args

    def test_to_dict_serializes_every_field(self) -> None:
        proposal = FollowupProposal(
            source_kind="coherence_issue",
            source_key="coherence_abc",
            title="t",
            body="b",
            labels=("epistemic", "coherence"),
            rationale="r",
            provenance={"kind": "contradiction", "belief_ids": ["b1", "b2"]},
        )
        assert proposal.to_dict() == {
            "source_kind": "coherence_issue",
            "source_key": "coherence_abc",
            "title": "t",
            "body": "b",
            "labels": ["epistemic", "coherence"],
            "rationale": "r",
            "provenance": {"kind": "contradiction", "belief_ids": ["b1", "b2"]},
        }

    def test_to_dict_does_not_alias_provenance(self) -> None:
        proposal = FollowupProposal(
            source_kind="crux",
            source_key="k",
            title="t",
            body="b",
            labels=(),
            rationale="r",
            provenance={"crux_id": "c1"},
        )
        d = proposal.to_dict()
        d["provenance"]["crux_id"] = "mutated"
        assert proposal.provenance == {"crux_id": "c1"}


class TestCruxProposal:
    def test_below_threshold_returns_none(self) -> None:
        low = _make_crux(score=0.3)
        assert propose_followup_for_crux(low) is None

    def test_above_threshold_produces_proposal(self) -> None:
        crux = _make_crux(score=0.85)
        proposal = propose_followup_for_crux(
            crux,
            cruxset_id="crxset_abc",
            question="should we ship?",
        )
        assert proposal is not None
        assert proposal.source_kind == "crux"
        assert "DIC-17" in proposal.title
        assert "X is load-bearing" in proposal.body
        assert "crxset_abc" in proposal.body
        assert "should we ship?" in proposal.body
        assert "Evidence gaps" in proposal.body
        assert "counterfactual" in proposal.body.lower()
        assert "boss-ready" not in proposal.labels
        assert "epistemic" in proposal.labels
        assert "crux" in proposal.labels
        assert proposal.provenance["crux_id"] == "c1"

    def test_long_statement_truncated_in_body(self) -> None:
        long = Crux(
            crux_id="c_long",
            statement="x " * 1000,
            positions=(CruxPosition(side="for", agents=("alice",)),),
            load_bearing_score=0.9,
        )
        proposal = propose_followup_for_crux(long)
        assert proposal is not None
        assert "…" in proposal.body  # truncation indicator present

    def test_title_length_capped(self) -> None:
        crux = Crux(
            crux_id="c_title",
            statement="Z" * 300,
            positions=(CruxPosition(side="for", agents=("alice",)),),
            load_bearing_score=0.9,
        )
        proposal = propose_followup_for_crux(crux)
        assert proposal is not None
        assert len(proposal.title) <= 140

    def test_extra_labels_added_but_boss_ready_stripped(self) -> None:
        crux = _make_crux()
        proposal = propose_followup_for_crux(
            crux,
            extra_labels=("p1", "boss-ready"),
        )
        assert proposal is not None
        assert "p1" in proposal.labels
        assert "boss-ready" not in proposal.labels

    def test_invalid_threshold_raises(self) -> None:
        crux = _make_crux()
        with pytest.raises(ValueError):
            propose_followup_for_crux(crux, load_bearing_threshold=1.5)

    def test_source_key_deterministic(self) -> None:
        crux = _make_crux()
        a = propose_followup_for_crux(crux, cruxset_id="crxset_a")
        b = propose_followup_for_crux(crux, cruxset_id="crxset_a")
        assert a is not None and b is not None
        assert a.source_key == b.source_key


class TestCruxSetProposal:
    def _cs(self) -> CruxSet:
        return CruxSet.build(
            question="should we ship?",
            cruxes=[
                _make_crux(crux_id="c1", score=0.9),
                _make_crux(crux_id="c2", score=0.75),
                _make_crux(crux_id="c3", score=0.3),  # below threshold
            ],
        )

    def test_top_k_caps_output_and_respects_threshold(self) -> None:
        cs = self._cs()
        proposals = propose_followup_for_cruxset(cs, top_k=3)
        # c1 and c2 clear threshold; c3 does not
        assert len(proposals) == 2
        assert [p.provenance["crux_id"] for p in proposals] == ["c1", "c2"]

    def test_top_k_smaller_than_load_bearing_count(self) -> None:
        cs = self._cs()
        proposals = propose_followup_for_cruxset(cs, top_k=1)
        assert len(proposals) == 1
        assert proposals[0].provenance["crux_id"] == "c1"

    def test_invalid_top_k_raises(self) -> None:
        cs = self._cs()
        with pytest.raises(ValueError):
            propose_followup_for_cruxset(cs, top_k=0)


class TestFailedClaimProposal:
    def test_large_loss_produces_proposal(self) -> None:
        claim, resolved, delta = _make_failed_settlement(probability=0.95, stake=50, outcome="no")
        # Brier = 0.95^2 = 0.9025 → payout = 1 - 2*0.9025 = -0.805 → delta ≈ -40.25
        assert delta.delta <= DEFAULT_DELTA_LOSS_THRESHOLD
        proposal = propose_followup_for_failed_claim(claim, resolved, delta)
        assert proposal is not None
        assert proposal.source_kind == "failed_claim"
        assert "high-loss prediction" in proposal.title
        assert "alice" in proposal.title
        assert claim.claim_id in proposal.body
        assert delta.delta_id in proposal.body
        assert "brier_proper" in proposal.body
        assert "boss-ready" not in proposal.labels

    def test_small_loss_below_threshold_returns_none(self) -> None:
        # Probability 0.8 on YES outcome NO: Brier=0.64, payout=-0.28, delta=-10*0.28=-2.8
        claim, resolved, delta = _make_failed_settlement(probability=0.8, stake=10, outcome="no")
        # Sanity: delta is negative but small
        assert -3.0 < delta.delta < 0.0
        # At a generous threshold the proposal fires
        lax = propose_followup_for_failed_claim(claim, resolved, delta, delta_loss_threshold=-1.0)
        assert lax is not None
        assert lax.source_kind == "failed_claim"
        # At a strict threshold it does not
        strict = propose_followup_for_failed_claim(
            claim, resolved, delta, delta_loss_threshold=-50.0
        )
        assert strict is None

    def test_inconclusive_outcome_returns_none(self) -> None:
        claim = StakeableClaim.create(
            agent_id="alice",
            domain=DOMAIN_PREDICTION_MARKET,
            statement="x",
            position="yes",
            stake_units=50,
            resolution_source="synthetic_github",
            resolution_id="mkt_x",
            predicted_probability=0.7,
        )
        resolved = ResolvedClaim(
            claim_id=claim.claim_id,
            outcome="inconclusive",
            resolved_at="2026-04-24T12:00:00Z",
            resolution_source="synthetic_github",
        )
        delta = settle_claim(claim, resolved, scoring_rule="brier_proper")
        # Inconclusive → delta == 0 regardless of threshold
        assert delta.delta == 0.0
        assert propose_followup_for_failed_claim(claim, resolved, delta) is None


class TestQueueGovernanceInvariants:
    """Regression guards for the DIC-17 acceptance shape."""

    def test_crux_proposal_never_carries_boss_ready(self) -> None:
        crux = _make_crux()
        # Even if the caller tries to inject boss-ready
        proposal = propose_followup_for_crux(
            crux, extra_labels=("boss-ready", "boss-ready", "epistemic")
        )
        assert proposal is not None
        assert "boss-ready" not in proposal.labels

    def test_failed_claim_proposal_never_carries_boss_ready(self) -> None:
        claim, resolved, delta = _make_failed_settlement()
        proposal = propose_followup_for_failed_claim(
            claim, resolved, delta, extra_labels=("boss-ready",)
        )
        assert proposal is not None
        assert "boss-ready" not in proposal.labels

    def test_proposals_are_deduplicable_by_source_key(self) -> None:
        # Same crux + cruxset_id → same source_key (deterministic dedup)
        crux = _make_crux()
        a = propose_followup_for_crux(crux, cruxset_id="crxset_a")
        b = propose_followup_for_crux(crux, cruxset_id="crxset_a")
        assert a is not None and b is not None
        assert a.source_key == b.source_key
        # Different cruxset_id → different source_key
        c = propose_followup_for_crux(crux, cruxset_id="crxset_b")
        assert c is not None
        assert a.source_key != c.source_key


class TestFeatureFlag:
    def test_disabled_by_default(self, monkeypatch) -> None:
        monkeypatch.delenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", raising=False)
        from aragora.epistemic import epistemic_followup_enabled

        assert epistemic_followup_enabled() is False

    def test_enable_helper(self, monkeypatch) -> None:
        monkeypatch.delenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", raising=False)
        from aragora.epistemic import enable_epistemic_followup, epistemic_followup_enabled

        assert epistemic_followup_enabled() is False
        enable_epistemic_followup()
        try:
            assert epistemic_followup_enabled() is True
        finally:
            monkeypatch.delenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", raising=False)
