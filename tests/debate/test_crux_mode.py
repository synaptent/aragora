"""Tests for the crux_finder consensus mode (Crux A1 / #6038).

The mode elevates existing CruxDetector output into a first-class debate
goal via a new `consensus="crux_finder"` setting. The deliverable is not a
verdict — it is a ranked map of load-bearing disagreements that, if
resolved, would most change the answer.
"""

from __future__ import annotations

import pytest

from aragora.debate.consensus import (
    ConsensusProof,
    build_proof_from_crux_finder,
)
from aragora.debate.crux_mode import CruxFinderResult, build_crux_finder_result
from aragora.debate.protocol import DebateProtocol
from aragora.reasoning.belief import BeliefNetwork
from aragora.reasoning.claims import RelationType
from aragora.reasoning.crux_detector import CruxAnalysisResult, CruxClaim


# ---------------------------------------------------------------------------
# 1. Protocol surface
# ---------------------------------------------------------------------------


def test_crux_finder_literal_accepted() -> None:
    """`DebateProtocol(consensus="crux_finder")` must construct without error.

    Protects the Literal extension from silent regressions (previous values
    only included the eight pre-CruxEngine modes).
    """
    proto = DebateProtocol(consensus="crux_finder")
    assert proto.consensus == "crux_finder"
    # Defaults should mirror CruxDetector.detect_cruxes + KM sync threshold.
    assert proto.crux_finder_top_k == 5
    assert proto.crux_finder_min_score == 0.3
    assert proto.crux_finder_counterfactual_validation is True


# ---------------------------------------------------------------------------
# 2. Result dataclass
# ---------------------------------------------------------------------------


def _sample_analysis() -> CruxAnalysisResult:
    return CruxAnalysisResult(
        cruxes=[
            CruxClaim(
                claim_id="c1",
                statement="Is the claim sound?",
                author="agent-alpha",
                crux_score=0.82,
                influence_score=0.7,
                disagreement_score=0.6,
                uncertainty_score=0.5,
                centrality_score=0.8,
                affected_claims=["c2"],
                contesting_agents=["agent-alpha", "agent-beta"],
                resolution_impact=0.4,
            )
        ],
        total_claims=3,
        total_disagreements=1,
        average_uncertainty=0.5,
        convergence_barrier=0.6,
        recommended_focus=["c1"],
    )


def test_crux_finder_result_serialization_round_trips() -> None:
    """`CruxFinderResult.to_dict()` must round-trip losslessly through JSON."""
    import json

    result = CruxFinderResult(
        debate_id="debate-xyz",
        question="Should we adopt X?",
        analysis=_sample_analysis(),
        counterfactuals=[
            {
                "claim_id": "c1",
                "condition": "Resolve 'Is the claim sound?' to high confidence",
                "outcome_change": "Reduces total network uncertainty by 0.400",
                "likelihood": 0.5,
                "affected_claims": ["c2"],
            }
        ],
        agents=["agent-alpha", "agent-beta"],
        rounds=3,
        raw_claims=[{"claim_id": "c1", "statement": "Is the claim sound?"}],
        metadata={"mode": "crux_finder", "approach": "A"},
    )

    payload = json.loads(json.dumps(result.to_dict()))
    assert payload["debate_id"] == "debate-xyz"
    assert payload["question"] == "Should we adopt X?"
    assert payload["analysis"]["total_claims"] == 3
    assert payload["analysis"]["cruxes"][0]["claim_id"] == "c1"
    assert payload["counterfactuals"][0]["affected_claims"] == ["c2"]
    assert payload["agents"] == ["agent-alpha", "agent-beta"]
    assert payload["rounds"] == 3
    assert payload["metadata"]["mode"] == "crux_finder"


def test_crux_finder_result_exposes_top_cruxes_and_barrier() -> None:
    result = CruxFinderResult(
        debate_id="d",
        question="q",
        analysis=_sample_analysis(),
        counterfactuals=[],
        agents=[],
        rounds=0,
    )
    assert result.top_cruxes() == result.analysis.cruxes
    assert result.convergence_barrier() == result.analysis.convergence_barrier


# ---------------------------------------------------------------------------
# 3. Proof builder
# ---------------------------------------------------------------------------


def test_build_proof_from_crux_finder_carries_sentinel_final_claim() -> None:
    """The proof's `final_claim` must be the `__CRUX_MAP__` sentinel.

    Downstream consumers that assume a verdict can detect this sentinel and
    route to the crux receipt instead. Any change to the sentinel string is
    breaking and must be caught by this test.
    """
    result = CruxFinderResult(
        debate_id="d1",
        question="What should we do?",
        analysis=_sample_analysis(),
        counterfactuals=[],
        agents=["agent-alpha", "agent-beta"],
        rounds=3,
    )
    proof = build_proof_from_crux_finder(result)

    assert isinstance(proof, ConsensusProof)
    assert proof.debate_id == "d1"
    assert proof.task == "What should we do?"
    assert proof.final_claim.startswith("__CRUX_MAP__")
    assert proof.consensus_reached is False, (
        "A crux-finder run is NOT a verdict by design; consensus_reached must "
        "be False so downstream gating treats it as 'no answer'."
    )
    assert proof.metadata.get("consensus_mode") == "crux_finder"
    # Cruxes surface as unresolved tensions.
    assert len(proof.unresolved_tensions) == len(result.analysis.cruxes)
    # Proof checksum must be stable / computable for signing.
    assert isinstance(proof.checksum, str) and len(proof.checksum) > 0


def test_build_proof_from_crux_finder_handles_empty_analysis() -> None:
    """An empty crux list must still produce a valid, serializable proof."""
    empty = CruxAnalysisResult(
        cruxes=[],
        total_claims=0,
        total_disagreements=0,
        average_uncertainty=0.0,
        convergence_barrier=0.0,
        recommended_focus=[],
    )
    result = CruxFinderResult(
        debate_id="d-empty",
        question="Trivial question",
        analysis=empty,
        counterfactuals=[],
        agents=[],
        rounds=0,
    )
    proof = build_proof_from_crux_finder(result)

    assert proof.final_claim.startswith("__CRUX_MAP__")
    assert proof.unresolved_tensions == []


# ---------------------------------------------------------------------------
# 4. End-to-end integration against a small BeliefNetwork
# ---------------------------------------------------------------------------


@pytest.fixture
def contested_network() -> BeliefNetwork:
    """Build a network with a heavily contested, influence-rich root claim.

    c1 has two downstream claims (so influence is high) and is connected
    to opposing claims from a different author (so disagreement is high).
    The CruxDetector should rank c1 near the top.
    """
    network = BeliefNetwork(debate_id="integration-test")
    network.add_claim("c1", "Load-bearing contested claim", "agent-alpha", 0.55)
    network.add_claim("c2", "Depends on c1", "agent-alpha", 0.7)
    network.add_claim("c3", "Also depends on c1", "agent-alpha", 0.4)
    network.add_claim("c4", "Counter-evidence against c1", "agent-beta", 0.6)
    network.add_claim("c5", "Supporting evidence for c1", "agent-gamma", 0.5)
    network.add_factor("c1", "c2", RelationType.SUPPORTS)
    network.add_factor("c1", "c3", RelationType.SUPPORTS)
    network.add_factor("c4", "c1", RelationType.CONTRADICTS)
    network.add_factor("c5", "c1", RelationType.SUPPORTS)
    return network


def test_build_crux_finder_result_produces_ranked_cruxes(
    contested_network: BeliefNetwork,
) -> None:
    protocol = DebateProtocol(consensus="crux_finder")
    result = build_crux_finder_result(
        belief_network=contested_network,
        protocol=protocol,
        debate_id="d-integration",
        question="Should we trust the contested claim?",
        agents=["agent-alpha", "agent-beta"],
        rounds=3,
    )

    assert isinstance(result, CruxFinderResult)
    assert result.debate_id == "d-integration"
    # A contested, influence-rich network must surface at least one crux.
    assert len(result.analysis.cruxes) >= 1
    # Ranked output — first crux score should dominate or equal the rest.
    scores = [c.crux_score for c in result.analysis.cruxes]
    assert scores == sorted(scores, reverse=True)
    # Counterfactual validation produces one record per crux.
    if protocol.crux_finder_counterfactual_validation:
        assert len(result.counterfactuals) == len(result.analysis.cruxes)
        for cf in result.counterfactuals:
            assert {"claim_id", "condition", "outcome_change", "likelihood"} <= cf.keys()


def test_build_crux_finder_result_requires_non_none_network() -> None:
    """Guard against silent fallback — design decision from Track A1."""
    protocol = DebateProtocol(consensus="crux_finder")
    with pytest.raises(RuntimeError, match="belief network"):
        build_crux_finder_result(
            belief_network=None,  # type: ignore[arg-type]
            protocol=protocol,
            debate_id="d",
            question="q",
            agents=[],
            rounds=0,
        )


def test_build_crux_finder_result_skips_counterfactuals_when_disabled(
    contested_network: BeliefNetwork,
) -> None:
    protocol = DebateProtocol(
        consensus="crux_finder",
        crux_finder_counterfactual_validation=False,
    )
    result = build_crux_finder_result(
        belief_network=contested_network,
        protocol=protocol,
        debate_id="d",
        question="q",
        agents=[],
        rounds=0,
    )
    assert result.counterfactuals == []


# ---------------------------------------------------------------------------
# 5. Dispatcher routing inside the consensus phase
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consensus_phase_dispatches_to_crux_finder(
    contested_network: BeliefNetwork,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ConsensusPhase._execute_consensus("crux_finder")` must run the
    crux-finder handler end-to-end and attach a ConsensusProof + the
    formal_verification["crux_finder"] summary to `ctx.result`.
    """
    monkeypatch.setenv("ARAGORA_CRUX_FINDER_ENABLED", "1")
    from types import SimpleNamespace
    from aragora.debate.phases.consensus_phase import ConsensusPhase

    protocol = DebateProtocol(consensus="crux_finder")

    # Minimal stub `ctx` — only the fields the handler reads.
    result = SimpleNamespace(
        debate_id="d-dispatcher",
        rounds_used=3,
        consensus_proof=None,
        consensus_reached=None,
        final_answer=None,
        consensus_strength=None,
        formal_verification=None,
    )
    env = SimpleNamespace(task="Should we adopt X?")
    ctx = SimpleNamespace(
        env=env,
        agents=[SimpleNamespace(name="agent-alpha"), SimpleNamespace(name="agent-beta")],
        result=result,
        debate_id="d-dispatcher",
        belief_network=contested_network,
    )

    phase = ConsensusPhase.__new__(ConsensusPhase)
    phase.protocol = protocol
    phase._notify_spectator = None
    phase.hooks = {}

    await phase._execute_consensus(ctx, "crux_finder")

    assert result.consensus_proof is not None
    assert result.consensus_proof.final_claim.startswith("__CRUX_MAP__")
    assert result.consensus_reached is False
    assert isinstance(result.formal_verification, dict)
    crux_summary = result.formal_verification["crux_finder"]
    assert crux_summary["crux_count"] >= 1
    assert "convergence_barrier" in crux_summary


@pytest.mark.asyncio
async def test_consensus_phase_records_crux_skip_metadata_without_belief_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI needs a machine-readable skip reason for operator-facing errors."""
    monkeypatch.setenv("ARAGORA_CRUX_FINDER_ENABLED", "1")
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from aragora.debate.phases.consensus_phase import ConsensusPhase

    protocol = DebateProtocol(consensus="crux_finder")
    result = SimpleNamespace(
        debate_id="d-no-network",
        rounds_used=0,
        consensus_proof=None,
        consensus_reached=None,
        final_answer=None,
        consensus_strength=None,
        formal_verification=None,
        metadata={},
    )
    ctx = SimpleNamespace(
        env=SimpleNamespace(task="Should demo agents produce cruxes?"),
        agents=[SimpleNamespace(name="demo")],
        result=result,
        debate_id="d-no-network",
        belief_network=None,
    )

    phase = ConsensusPhase.__new__(ConsensusPhase)
    phase.protocol = protocol
    phase._notify_spectator = None
    phase.hooks = {}
    phase._handle_majority_consensus = AsyncMock()

    await phase._execute_consensus(ctx, "crux_finder")

    assert result.metadata["crux_finder_skipped_reason"] == "no_belief_network"
    assert result.metadata["crux_finder_fallback_consensus"] == "majority"
    phase._handle_majority_consensus.assert_awaited_once_with(ctx)


@pytest.mark.asyncio
async def test_consensus_phase_seeds_current_debate_claims_for_crux_finder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real contested debate must not sign an empty crux map."""
    monkeypatch.setenv("ARAGORA_CRUX_FINDER_ENABLED", "1")
    from types import SimpleNamespace

    from aragora.core import Message
    from aragora.debate.phases.consensus_phase import ConsensusPhase

    protocol = DebateProtocol(consensus="crux_finder")
    result = SimpleNamespace(
        debate_id="d-current",
        rounds_used=1,
        consensus_proof=None,
        consensus_reached=None,
        final_answer=None,
        consensus_strength=None,
        formal_verification=None,
        messages=[
            Message(
                role="proposer",
                agent="agent-alpha",
                content=(
                    "We should approve Project Atlas because it clearly reduces "
                    "support cost and improves reliability."
                ),
            ),
            Message(
                role="critic",
                agent="agent-beta",
                content=(
                    "We should reject Project Atlas because it increases migration "
                    "risk and could degrade reliability."
                ),
            ),
        ],
    )
    ctx = SimpleNamespace(
        env=SimpleNamespace(task="Should we approve Project Atlas?"),
        agents=[SimpleNamespace(name="agent-alpha"), SimpleNamespace(name="agent-beta")],
        result=result,
        debate_id="d-current",
        belief_network=BeliefNetwork(debate_id="d-current"),
        proposals={
            "agent-alpha": result.messages[0].content,
            "agent-beta": result.messages[1].content,
        },
        context_messages=result.messages,
    )

    phase = ConsensusPhase.__new__(ConsensusPhase)
    phase.protocol = protocol
    phase._notify_spectator = None
    phase.hooks = {}

    await phase._execute_consensus(ctx, "crux_finder")

    crux_summary = result.formal_verification["crux_finder"]
    assert crux_summary["crux_count"] >= 1
    assert result.consensus_proof.metadata["current_debate_claim_count"] >= 2
    assert result.consensus_proof.metadata["belief_network_claim_count"] >= 3
    assert result.consensus_proof.metadata["recommended_focus"]
