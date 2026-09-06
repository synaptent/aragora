"""Tests for DIC-22 repair-spec → debate adapter (aragora.epistemic.repair_debate).

Covers: flag gate, empty-agents guard, consensus math, CruxReceipt content,
linked crux propagation, no-hot-swap proof, and serialisation.
All tests run without network access or real LLM keys.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from aragora.epistemic.decay_monitor import DecayReason, DecaySignal
from aragora.epistemic.repair import propose_repair
from aragora.epistemic.repair_debate import RepairDebateResult, run_repair_debate


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _signal() -> DecaySignal:
    return DecaySignal(
        code_unit_id="unit.proof.test",
        integrity_score=0.35,
        reasons=[
            DecayReason(kind="failed_claim", detail="claim expired", claim_id="claim.b0.fresh"),
            DecayReason(kind="unresolved_crux", detail="", crux_id="crux.soak.policy"),
        ],
        recommended_action="repair_required",
    )


def _spec(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ARAGORA_REPAIR_PIPELINE_ENABLED", "1")
    return propose_repair(
        _signal(),
        repair_kind="pr_candidate",
        validation_commands=["pytest tests/epistemic/"],
    )


class _SupportAgent:
    name = "mock-support"

    def evaluate(self, spec, context):
        return {
            "supports_repair": True,
            "crux_candidates": [
                {
                    "crux_id": "crux.mock.boundary",
                    "statement": "Is the patch within safe scope?",
                    "load_bearing_score": 0.8,
                    "uncertainty_score": 0.3,
                    "resolution_impact": 0.7,
                }
            ],
            "notes": "Repair is bounded and claim-linked.",
        }


class _OpposeAgent:
    name = "mock-oppose"

    def evaluate(self, spec, context):
        return {"supports_repair": False, "crux_candidates": [], "notes": "Needs more evidence."}


class _StringSupportAgent:
    name = "mock-string-support"

    def evaluate(self, spec, context):
        return {"supports_repair": "false", "crux_candidates": []}


class _NamedCruxAgent:
    def __init__(self, name: str, **scores) -> None:
        self.name = name
        self.scores = scores

    def evaluate(self, spec, context):
        return {
            "supports_repair": True,
            "crux_candidates": [
                {
                    "crux_id": "crux.shared",
                    "statement": "Shared concern",
                    **self.scores,
                }
            ],
        }


class _MalformedCandidatesAgent:
    name = "mock-malformed-candidates"

    def __init__(self, candidates) -> None:
        self.candidates = candidates

    def evaluate(self, spec, context):
        return {"supports_repair": False, "crux_candidates": self.candidates}


class _ContextMutatingAgent:
    name = "mock-context-mutator"

    def evaluate(self, spec, context):
        context["linked_claims"].append("mutated-claim")
        context["linked_crux_ids"].append("mutated-crux")
        context["validation_commands"].append("rm -rf ignored")
        return {"supports_repair": False, "crux_candidates": []}


# ---------------------------------------------------------------------------
# Flag gate
# ---------------------------------------------------------------------------


class TestFlagGate:
    def test_requires_pipeline_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARAGORA_REPAIR_PIPELINE_ENABLED", raising=False)
        sig = _signal()
        spec = propose_repair(sig)  # report_only is always allowed
        with pytest.raises(RuntimeError, match="ARAGORA_REPAIR_PIPELINE_ENABLED"):
            run_repair_debate(spec, [_SupportAgent()])

    def test_empty_agents_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        with pytest.raises(ValueError, match="at least one agent"):
            run_repair_debate(spec, [])


# ---------------------------------------------------------------------------
# Consensus arithmetic
# ---------------------------------------------------------------------------


class TestConsensus:
    def test_majority_support_reaches_consensus(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_SupportAgent(), _SupportAgent(), _OpposeAgent()])
        assert result.consensus_reached
        assert result.recommended_action == "proceed_with_repair"

    def test_majority_oppose_blocks_consensus(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_OpposeAgent(), _OpposeAgent(), _SupportAgent()])
        assert not result.consensus_reached
        assert result.recommended_action == "request_human_review"

    def test_single_supporting_agent_is_consensus(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_SupportAgent()])
        assert result.consensus_reached

    def test_single_opposing_agent_blocks_consensus(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_OpposeAgent()])
        assert not result.consensus_reached

    def test_tie_blocks_consensus(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_SupportAgent(), _OpposeAgent()])
        assert not result.consensus_reached

    def test_truthy_non_boolean_support_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_StringSupportAgent()])
        assert not result.consensus_reached
        assert result.recommended_action == "request_human_review"

    def test_convergence_barrier_zero_on_consensus(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_SupportAgent()])
        assert result.receipt.convergence_barrier == 0.0

    def test_convergence_barrier_one_on_no_consensus(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_OpposeAgent()])
        assert result.receipt.convergence_barrier == 1.0


# ---------------------------------------------------------------------------
# CruxReceipt content
# ---------------------------------------------------------------------------


class TestReceipt:
    def test_receipt_has_64char_sha256_checksum(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_SupportAgent()])
        assert len(result.receipt.checksum) == 64
        assert all(c in "0123456789abcdef" for c in result.receipt.checksum)

    def test_receipt_checksum_uses_canonical_crux_serialization(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = _spec(monkeypatch)
        receipt = run_repair_debate(spec, [_SupportAgent()]).receipt
        material = {
            "receipt_id": receipt.receipt_id,
            "debate_id": receipt.debate_id,
            "question": receipt.question,
            "cruxes": [crux.to_dict() for crux in receipt.cruxes],
            "convergence_barrier": round(receipt.convergence_barrier, 4),
        }
        expected = hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        assert receipt.checksum == expected

    def test_receipt_links_spec_metadata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_SupportAgent()])
        meta = result.receipt.metadata
        assert meta["spec_id"] == spec.spec_id
        assert meta["code_unit_id"] == spec.code_unit_id
        assert meta["repair_kind"] == spec.repair_kind
        assert meta["repair_provenance_hash"] == spec.provenance_hash

    def test_receipt_debate_id_contains_spec_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_SupportAgent()])
        assert result.receipt.debate_id == f"repair-debate-{spec.spec_id}"

    def test_receipt_agent_names_recorded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_SupportAgent(), _OpposeAgent()])
        assert set(result.receipt.agents) == {"mock-support", "mock-oppose"}

    def test_receipt_rounds_is_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_SupportAgent()])
        assert result.receipt.rounds == 1

    def test_result_serialization_preserves_complete_receipt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_SupportAgent()])
        assert result.to_dict()["receipt"] == result.receipt.to_dict()


# ---------------------------------------------------------------------------
# Crux entry propagation
# ---------------------------------------------------------------------------


class TestCruxPropagation:
    def test_agent_crux_candidates_included(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_SupportAgent()])
        crux_ids = {c.crux_id for c in result.receipt.cruxes}
        assert "crux.mock.boundary" in crux_ids

    def test_spec_linked_crux_ids_included(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_SupportAgent()])
        crux_ids = {c.crux_id for c in result.receipt.cruxes}
        assert "crux.soak.policy" in crux_ids

    def test_no_duplicate_crux_ids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_SupportAgent(), _SupportAgent()])
        crux_ids = [c.crux_id for c in result.receipt.cruxes]
        assert len(crux_ids) == len(set(crux_ids))

    def test_duplicate_crux_collects_all_contesting_agents(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(
            spec,
            [_NamedCruxAgent("agent-a"), _NamedCruxAgent("agent-b")],
        )
        shared = next(crux for crux in result.receipt.cruxes if crux.crux_id == "crux.shared")
        assert shared.contesting_agents == ["agent-a", "agent-b"]

    def test_zero_scores_are_preserved_and_malformed_scores_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(
            spec,
            [
                _NamedCruxAgent(
                    "agent-a",
                    load_bearing_score=0.0,
                    uncertainty_score="high",
                    resolution_impact=None,
                )
            ],
        )
        shared = next(crux for crux in result.receipt.cruxes if crux.crux_id == "crux.shared")
        assert shared.load_bearing_score == 0.0
        assert shared.uncertainty_score == 0.5
        assert shared.resolution_impact == 0.5

    @pytest.mark.parametrize(
        ("scores", "expected"),
        [
            ({"load_bearing_score": float("nan")}, 0.5),
            ({"load_bearing_score": float("inf")}, 0.5),
            ({"load_bearing_score": -0.25}, 0.0),
            ({"load_bearing_score": 1.25}, 1.0),
        ],
    )
    def test_non_finite_scores_default_and_finite_scores_are_clamped(
        self,
        monkeypatch: pytest.MonkeyPatch,
        scores: dict[str, float],
        expected: float,
    ) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_NamedCruxAgent("agent-a", **scores)])
        shared = next(crux for crux in result.receipt.cruxes if crux.crux_id == "crux.shared")
        assert shared.load_bearing_score == expected
        json.dumps(result.receipt.to_dict(), allow_nan=False)

    @pytest.mark.parametrize("candidates", [None, "not-a-list", ["not-a-dict"]])
    def test_malformed_crux_candidates_are_treated_as_empty(
        self, monkeypatch: pytest.MonkeyPatch, candidates
    ) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_MalformedCandidatesAgent(candidates)])
        assert {crux.crux_id for crux in result.receipt.cruxes} == set(spec.linked_crux_ids)

    def test_agent_cannot_mutate_repair_spec_through_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = _spec(monkeypatch)
        original_claims = list(spec.linked_claims)
        original_crux_ids = list(spec.linked_crux_ids)
        original_commands = list(spec.validation_commands)
        result = run_repair_debate(spec, [_ContextMutatingAgent()])
        assert spec.linked_claims == original_claims
        assert spec.linked_crux_ids == original_crux_ids
        assert spec.validation_commands == original_commands
        assert all(crux.affected_claims == original_claims for crux in result.receipt.cruxes)

    def test_crux_affected_claims_match_spec(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_SupportAgent()])
        for entry in result.receipt.cruxes:
            assert entry.affected_claims == spec.linked_claims

    def test_empty_crux_candidates_still_includes_signal_cruxes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_OpposeAgent()])
        crux_ids = {c.crux_id for c in result.receipt.cruxes}
        assert "crux.soak.policy" in crux_ids


# ---------------------------------------------------------------------------
# No-hot-swap proof
# ---------------------------------------------------------------------------


class TestNoHotswap:
    def test_recommended_action_is_bounded_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        for agents in ([_SupportAgent()], [_OpposeAgent()]):
            result = run_repair_debate(spec, agents)
            assert result.recommended_action in {"proceed_with_repair", "request_human_review"}

    def test_result_carries_no_live_routing_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_SupportAgent()])
        d = result.to_dict()
        for key in d:
            assert "live" not in key.lower(), f"Unexpected live-routing key: {key!r}"

    def test_spec_repair_kind_not_live_swap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        assert spec.repair_kind != "live_swap"


# ---------------------------------------------------------------------------
# Question override and serialisation
# ---------------------------------------------------------------------------


class TestMisc:
    def test_question_override_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_SupportAgent()], question_override="Is it safe?")
        assert result.receipt.question == "Is it safe?"

    def test_default_question_contains_spec_id_substring(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_SupportAgent()])
        assert spec.code_unit_id in result.receipt.question

    def test_spec_id_on_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_SupportAgent()])
        assert result.spec_id == spec.spec_id

    def test_to_dict_round_trips(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(monkeypatch)
        result = run_repair_debate(spec, [_SupportAgent()])
        d = result.to_dict()
        assert d["spec_id"] == spec.spec_id
        assert d["consensus_reached"] is True
        assert d["recommended_action"] == "proceed_with_repair"
        assert "receipt" in d
        assert len(d["receipt"]["checksum"]) == 64
        assert "cruxes" in d["receipt"]
        assert isinstance(d["agent_evaluations"], list)
