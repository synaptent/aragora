# tests/debate/test_taint_tracking.py
"""Tests for G2 trust-tier taint tracking in debate orchestrator."""

import pytest


class TestAgentProposalTaint:
    def test_default_trust_tier_is_standard(self):
        from aragora.debate.distributed_events import AgentProposal

        p = AgentProposal(agent_id="claude", instance_id="i1", content="test", round_number=1)
        assert p.trust_tier == "standard"
        assert p.taint_source is None
        assert p.taint_evidence == []

    def test_untrusted_tier_can_be_set(self):
        from aragora.debate.distributed_events import AgentProposal

        p = AgentProposal(
            agent_id="claude",
            instance_id="i1",
            content="test",
            round_number=1,
            trust_tier="untrusted",
            taint_source="retrieved_context",
            taint_evidence=["ev-001"],
        )
        assert p.trust_tier == "untrusted"
        assert p.taint_source == "retrieved_context"
        assert "ev-001" in p.taint_evidence

    def test_to_dict_includes_taint_fields(self):
        from aragora.debate.distributed_events import AgentProposal

        p = AgentProposal(
            agent_id="claude",
            instance_id="i1",
            content="test",
            round_number=1,
            trust_tier="untrusted",
            taint_source="config_file",
        )
        d = p.to_dict()
        assert "trust_tier" in d
        assert d["trust_tier"] == "untrusted"
        assert "taint_source" in d


class TestConsensusProofTaint:
    def test_default_trust_score_is_one(self):
        from aragora.gauntlet.receipt_models import ConsensusProof

        cp = ConsensusProof(reached=True, confidence=0.9)
        assert cp.trust_score == 1.0
        assert cp.tainted_proposals == []

    def test_tainted_proposals_can_be_recorded(self):
        from aragora.gauntlet.receipt_models import ConsensusProof

        cp = ConsensusProof(
            reached=True,
            confidence=0.9,
            tainted_proposals=["prop-001"],
            trust_score=0.67,
        )
        assert len(cp.tainted_proposals) == 1
        assert cp.trust_score == pytest.approx(0.67)

    def test_to_dict_includes_taint_fields(self):
        from aragora.gauntlet.receipt_models import ConsensusProof

        cp = ConsensusProof(
            reached=True,
            confidence=0.9,
            tainted_proposals=["prop-001"],
            trust_score=0.67,
        )
        d = cp.to_dict()
        assert "trust_score" in d
        assert "tainted_proposals" in d


class TestDecisionReceiptTaintAnalysis:
    def test_taint_analysis_defaults_to_none(self):
        from aragora.gauntlet.receipt_models import DecisionReceipt

        r = DecisionReceipt(
            receipt_id="r1",
            gauntlet_id="g1",
            timestamp="2026-01-01T00:00:00Z",
            input_summary="test",
            input_hash="abc",
            risk_summary={},
            attacks_attempted=0,
            attacks_successful=0,
            probes_run=0,
            vulnerabilities_found=0,
            verdict="PASS",
            confidence=0.9,
            robustness_score=0.8,
        )
        assert r.taint_analysis is None

    def test_taint_analysis_can_be_set(self):
        from aragora.gauntlet.receipt_models import DecisionReceipt

        taint = {
            "taint_level": "low",
            "tainted_proposal_count": 1,
            "trust_score": 0.75,
            "sources": ["retrieved_context"],
            "recommendation": "proceed",
        }
        r = DecisionReceipt(
            receipt_id="r1",
            gauntlet_id="g1",
            timestamp="2026-01-01T00:00:00Z",
            input_summary="test",
            input_hash="abc",
            risk_summary={},
            attacks_attempted=0,
            attacks_successful=0,
            probes_run=0,
            vulnerabilities_found=0,
            verdict="PASS",
            confidence=0.9,
            robustness_score=0.8,
            taint_analysis=taint,
        )
        assert r.taint_analysis["taint_level"] == "low"
        assert r.taint_analysis["recommendation"] == "proceed"


class TestTaintLevelComputation:
    """Tests for the taint_level computation helper."""

    def test_no_taint_when_trust_score_high(self):
        from aragora.debate.taint import compute_taint_analysis

        result = compute_taint_analysis(tainted_proposals=[], total_proposals=5)
        assert result["taint_level"] == "none"
        assert result["recommendation"] == "proceed"

    def test_low_taint_level(self):
        from aragora.debate.taint import compute_taint_analysis

        # 1 out of 5 tainted = trust_score 0.8 -> "low"
        result = compute_taint_analysis(
            tainted_proposals=["p1"],
            total_proposals=5,
            taint_sources=["retrieved_context"],
        )
        assert result["taint_level"] == "low"
        assert result["trust_score"] == pytest.approx(0.8)

    def test_high_taint_requires_human_approval(self):
        from aragora.debate.taint import compute_taint_analysis

        # 4 out of 5 tainted = trust_score 0.2 -> "high"
        result = compute_taint_analysis(
            tainted_proposals=["p1", "p2", "p3", "p4"],
            total_proposals=5,
        )
        assert result["taint_level"] == "high"
        assert result["recommendation"] == "human approval required"
