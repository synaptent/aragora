"""Tests for three-axis epistemic tags."""

from aragora.reasoning.epistemics import (
    AUTHORITY_RANK,
    EpistemicTag,
    KnowledgeState,
    ProvenanceClass,
    reconcile,
)


def _tag(state=KnowledgeState.KNOWN, prov=ProvenanceClass.OBSERVED, **kw) -> EpistemicTag:
    return EpistemicTag(state=state, provenance=prov, **kw)


class TestAuthorityRank:
    def test_observed_outranks_everything(self):
        observed = AUTHORITY_RANK[ProvenanceClass.OBSERVED]
        for prov in ProvenanceClass:
            assert observed <= AUTHORITY_RANK[prov]

    def test_derived_and_predicted_are_weakest(self):
        assert AUTHORITY_RANK[ProvenanceClass.DERIVED] > AUTHORITY_RANK[ProvenanceClass.REMEMBERED]
        assert AUTHORITY_RANK[ProvenanceClass.PREDICTED] > AUTHORITY_RANK[ProvenanceClass.DERIVED]

    def test_every_provenance_class_has_a_rank(self):
        assert set(AUTHORITY_RANK) == set(ProvenanceClass)


class TestEffectiveState:
    def test_known_within_ttl_stays_known(self):
        tag = _tag(observed_at=1000.0, ttl_seconds=60.0)
        assert tag.effective_state(now=1030.0) is KnowledgeState.KNOWN

    def test_known_past_ttl_degrades_to_stale(self):
        tag = _tag(observed_at=1000.0, ttl_seconds=60.0)
        assert tag.effective_state(now=1061.0) is KnowledgeState.STALE

    def test_estimated_past_ttl_degrades_to_stale(self):
        tag = _tag(state=KnowledgeState.ESTIMATED, observed_at=1000.0, ttl_seconds=60.0)
        assert tag.effective_state(now=1061.0) is KnowledgeState.STALE

    def test_conflicted_never_silently_improves(self):
        tag = _tag(state=KnowledgeState.CONFLICTED, observed_at=1000.0, ttl_seconds=60.0)
        assert tag.effective_state(now=1061.0) is KnowledgeState.CONFLICTED

    def test_no_ttl_means_no_decay(self):
        tag = _tag(observed_at=1000.0)
        assert tag.effective_state(now=10_000_000.0) is KnowledgeState.KNOWN


class TestReconcile:
    def test_ready_claim_vs_blocked_live_fact_is_conflicted(self):
        """The measured failure: a derived recommendation says 'ready' while
        the observed settlement state says 'blocked'. The observed value wins
        and the result is marked CONFLICTED so no consumer treats it as settled."""
        claimed = _tag(
            state=KnowledgeState.ESTIMATED, prov=ProvenanceClass.DERIVED, basis=["work:rec:42"]
        )
        live = _tag(prov=ProvenanceClass.OBSERVED, basis=["gh:pr:9932:mergeStateStatus"])
        value, tag = reconcile("ready", claimed, "blocked", live)
        assert value == "blocked"
        assert tag.state is KnowledgeState.CONFLICTED
        assert tag.provenance is ProvenanceClass.OBSERVED
        assert "work:rec:42" in tag.basis and "gh:pr:9932:mergeStateStatus" in tag.basis

    def test_agreement_keeps_higher_authority_tag_unmarked(self):
        claimed = _tag(state=KnowledgeState.ESTIMATED, prov=ProvenanceClass.DERIVED)
        live = _tag(prov=ProvenanceClass.OBSERVED)
        value, tag = reconcile("green", claimed, "green", live)
        assert value == "green"
        assert tag.state is KnowledgeState.KNOWN
        assert tag.provenance is ProvenanceClass.OBSERVED

    def test_higher_authority_claim_beats_lower_authority_live(self):
        claimed = _tag(prov=ProvenanceClass.OPERATOR_ASSERTED)
        live = _tag(state=KnowledgeState.ESTIMATED, prov=ProvenanceClass.PREDICTED)
        value, tag = reconcile("halt", claimed, "proceed", live)
        assert value == "halt"
        assert tag.state is KnowledgeState.CONFLICTED


class TestSerialization:
    def test_to_dict_round_trips_enum_values_as_strings(self):
        tag = _tag(observed_at=5.0, ttl_seconds=10.0, basis=["a"])
        d = tag.to_dict()
        assert d["state"] == "known"
        assert d["provenance"] == "observed"
        assert d["disposition"] is None
        assert d["observed_at"] == 5.0
        assert d["basis"] == ["a"]
