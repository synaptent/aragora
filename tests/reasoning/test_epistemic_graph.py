"""Tests for EpistemicGraph — cross-debate belief inheritance (AGT-01 / #6062).

Pure unit tests: no network, no subprocess, no queue mutation.
All graph state is in-memory; the singleton is reset around each test via
the autouse fixture below.

The EpistemicGraph is the belief-inheritance substrate the CruxDetector
relies on across debates once ARAGORA_CRUXSET_EMISSION_ENABLED is active.

Flag: ARAGORA_CRUXSET_EMISSION_ENABLED (default off). These tests run with
no flag set; they exercise the data model and graph operations directly
without touching the debate live path.
"""

from __future__ import annotations

import pytest

from aragora.reasoning.epistemic_graph import (
    EpistemicGraph,
    InheritedBelief,
    get_epistemic_graph,
    reset_epistemic_graph,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_epistemic_graph()
    yield
    reset_epistemic_graph()


# ---------------------------------------------------------------------------
# InheritedBelief
# ---------------------------------------------------------------------------


class TestInheritedBelief:
    def test_effective_confidence_scales_with_decay(self) -> None:
        b = InheritedBelief(
            belief_id="b1",
            statement="X is true",
            confidence=0.8,
            source_debate_id="d1",
            decay_factor=0.5,
        )
        assert b.effective_confidence == pytest.approx(0.4)

    def test_roundtrip_to_from_dict(self) -> None:
        b = InheritedBelief(
            belief_id="b3",
            statement="Z holds",
            confidence=0.9,
            source_debate_id="d2",
            source_type="dissent",
            domain="billing",
            supporting_agents=["alice"],
            dissenting_agents=["bob"],
        )
        r = InheritedBelief.from_dict(b.to_dict())
        assert r.belief_id == b.belief_id
        assert r.confidence == pytest.approx(b.confidence)
        assert r.source_type == b.source_type
        assert r.supporting_agents == b.supporting_agents
        assert r.dissenting_agents == b.dissenting_agents


# ---------------------------------------------------------------------------
# EpistemicGraph.absorb_consensus
# ---------------------------------------------------------------------------


class TestAbsorbConsensus:
    def test_produces_main_consensus_belief(self) -> None:
        g = EpistemicGraph()
        beliefs = g.absorb_consensus(
            debate_id="d1",
            final_claim="Rate limiting prevents abuse",
            confidence=0.85,
        )
        assert beliefs
        main = beliefs[0]
        assert main.source_type == "consensus"
        assert main.confidence == pytest.approx(0.85)

    def test_claim_beliefs_are_confidence_modulated(self) -> None:
        g = EpistemicGraph()
        beliefs = g.absorb_consensus(
            debate_id="d2",
            final_claim="Main verdict",
            confidence=0.5,
            claims=[{"statement": "Claim A", "confidence": 0.8, "author": "alice"}],
        )
        claim_belief = next(b for b in beliefs if b.source_type == "claim")
        assert claim_belief.confidence == pytest.approx(0.8 * 0.5)

    def test_domain_indexed_and_beliefs_stored(self) -> None:
        g = EpistemicGraph()
        beliefs = g.absorb_consensus(
            debate_id="d4",
            final_claim="X",
            confidence=0.7,
            domain="infrastructure",
        )
        assert "infrastructure" in g._domain_index
        assert all(g.get_belief(b.belief_id) is not None for b in beliefs)

    def test_claim_links_to_consensus_via_supports_edge(self) -> None:
        g = EpistemicGraph()
        beliefs = g.absorb_consensus(
            debate_id="d5",
            final_claim="Top verdict",
            confidence=0.8,
            claims=[{"statement": "Sub-claim", "confidence": 0.6, "author": "carol"}],
        )
        main_id = beliefs[0].belief_id
        edges = g.get_edges_for(main_id)
        assert any(e.relation == "supports" and e.target_id == main_id for e in edges)


# ---------------------------------------------------------------------------
# EpistemicGraph.absorb_dissent
# ---------------------------------------------------------------------------


class TestAbsorbDissent:
    def test_dissent_belief_has_correct_source_type(self) -> None:
        g = EpistemicGraph()
        d = g.absorb_dissent(
            debate_id="d1",
            dissent_statement="I disagree",
            dissenting_agent="bob",
        )
        assert d.source_type == "dissent"
        assert "bob" in d.dissenting_agents

    def test_dissent_reduces_related_belief_confidence(self) -> None:
        g = EpistemicGraph()
        original = 0.9
        beliefs = g.absorb_consensus(debate_id="d1", final_claim="X is right", confidence=original)
        main_id = beliefs[0].belief_id
        g.absorb_dissent(
            debate_id="d2",
            dissent_statement="X is wrong",
            dissenting_agent="bob",
            severity=0.5,
            related_belief_id=main_id,
        )
        updated = g.get_belief(main_id)
        assert updated is not None
        assert updated.confidence < original

    def test_contradicts_edge_links_dissent_to_related_belief(self) -> None:
        g = EpistemicGraph()
        main_id = g.absorb_consensus(debate_id="d1", final_claim="X", confidence=0.8)[0].belief_id
        d = g.absorb_dissent(
            debate_id="d2",
            dissent_statement="not X",
            dissenting_agent="bob",
            related_belief_id=main_id,
        )
        assert any(b.belief_id == d.belief_id for b in g.get_contradictions(main_id))


# ---------------------------------------------------------------------------
# EpistemicGraph.inject_priors
# ---------------------------------------------------------------------------


class TestInjectPriors:
    def test_returns_beliefs_matching_topic_keyword(self) -> None:
        g = EpistemicGraph()
        g.absorb_consensus(
            debate_id="d1",
            final_claim="database sharding reduces latency",
            confidence=0.8,
        )
        priors = g.inject_priors(topic="database latency")
        assert any(
            "database" in p.statement.lower() or "latency" in p.statement.lower() for p in priors
        )

    def test_limit_caps_returned_beliefs_and_sorted_by_confidence(self) -> None:
        g = EpistemicGraph()
        for i in range(6):
            g.absorb_consensus(
                debate_id=f"d{i}",
                final_claim=f"rate limit scenario {i}",
                confidence=0.8,
            )
        priors = g.inject_priors(topic="rate limit", limit=2)
        assert len(priors) <= 2

    def test_low_confidence_beliefs_pruned_after_decay(self) -> None:
        g = EpistemicGraph(decay_rate=0.01, min_confidence=0.5)
        g.absorb_consensus(debate_id="d1", final_claim="cache warms fast", confidence=0.6)
        assert g.stats()["total_beliefs"] == 1
        # _apply_decay runs inside inject_priors: 0.6 * 0.01 = 0.006 < 0.5 → pruned
        g.inject_priors(topic="cache")
        assert g.stats()["total_beliefs"] == 0


# ---------------------------------------------------------------------------
# EpistemicGraph.supersede
# ---------------------------------------------------------------------------


class TestSupersede:
    def test_old_belief_confidence_drastically_reduced(self) -> None:
        g = EpistemicGraph()
        old_id = g.absorb_consensus(debate_id="d1", final_claim="Old way", confidence=0.9)[
            0
        ].belief_id
        new_id = g.absorb_consensus(debate_id="d2", final_claim="New way", confidence=0.9)[
            0
        ].belief_id
        g.supersede(old_belief_id=old_id, new_belief_id=new_id, debate_id="d2")
        old = g.get_belief(old_id)
        assert old is not None
        assert old.confidence < 0.2
        assert old.metadata.get("superseded_by") == new_id

    def test_supersedes_edge_points_from_new_to_old(self) -> None:
        g = EpistemicGraph()
        old_id = g.absorb_consensus(debate_id="d1", final_claim="Old", confidence=0.8)[0].belief_id
        new_id = g.absorb_consensus(debate_id="d2", final_claim="New", confidence=0.8)[0].belief_id
        g.supersede(old_belief_id=old_id, new_belief_id=new_id)
        assert any(
            e.relation == "supersedes" and e.target_id == old_id for e in g.get_edges_for(new_id)
        )


# ---------------------------------------------------------------------------
# EpistemicGraph.stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_empty_graph_returns_zero_stats(self) -> None:
        g = EpistemicGraph()
        s = g.stats()
        assert s["total_beliefs"] == 0
        assert s["total_edges"] == 0
        assert s["avg_confidence"] == 0.0

    def test_stats_reflect_absorbed_beliefs_and_domains(self) -> None:
        g = EpistemicGraph()
        g.absorb_consensus(debate_id="d1", final_claim="X", confidence=0.8, domain="billing")
        s = g.stats()
        assert s["total_beliefs"] >= 1
        assert s["by_type"]["consensus"] >= 1
        assert "billing" in s["domains"]


# ---------------------------------------------------------------------------
# Serialisation round-trip
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_roundtrip_preserves_beliefs_and_config(self) -> None:
        g = EpistemicGraph(decay_rate=0.9, min_confidence=0.2)
        g.absorb_consensus(
            debate_id="rt",
            final_claim="Round-trip verdict",
            confidence=0.75,
            domain="testing",
            claims=[{"statement": "Sub-claim", "confidence": 0.6, "author": "alice"}],
        )
        g2 = EpistemicGraph.from_dict(g.to_dict())
        assert len(g2._beliefs) == len(g._beliefs)
        assert g2.decay_rate == pytest.approx(g.decay_rate)
        assert g2.min_confidence == pytest.approx(g.min_confidence)

    def test_from_dict_empty_data_yields_empty_graph(self) -> None:
        g = EpistemicGraph.from_dict({})
        assert g._beliefs == {}
        assert g._edges == []


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_returns_same_instance(self) -> None:
        assert get_epistemic_graph() is get_epistemic_graph()

    def test_reset_creates_fresh_instance(self) -> None:
        g1 = get_epistemic_graph()
        reset_epistemic_graph()
        assert get_epistemic_graph() is not g1

    def test_state_persists_across_singleton_calls(self) -> None:
        get_epistemic_graph().absorb_consensus(
            debate_id="d1",
            final_claim="Persisted belief",
            confidence=0.9,
        )
        assert get_epistemic_graph().stats()["total_beliefs"] >= 1
