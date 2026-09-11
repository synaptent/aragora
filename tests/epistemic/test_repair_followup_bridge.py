"""Tests for the DIC-22 → DIC-17 bridge: propose_followup_for_repair_spec.

Verifies that a RepairSpec produced by the DIC-22 repair pipeline can be
converted into a DIC-17 FollowupProposal with correct queue-governance
invariants (no boss-ready, correct source_kind, deterministic source_key,
provenance fields preserved).

Issue: #6033 (DIC-22), #6027 (DIC-17).
Flag: ARAGORA_REPAIR_PIPELINE_ENABLED (required for non-report_only specs).
"""

from __future__ import annotations

import pytest

from aragora.epistemic.decay_monitor import DecayReason, DecaySignal
from aragora.epistemic.followup import FollowupProposal, propose_followup_for_repair_spec
from aragora.epistemic.repair import enable_repair_pipeline, propose_repair


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _signal(
    code_unit_id: str = "unit.test.fn",
    integrity_score: float = 0.42,
    claim_id: str = "claim.test",
    crux_id: str = "crux.test",
) -> DecaySignal:
    return DecaySignal(
        code_unit_id=code_unit_id,
        integrity_score=integrity_score,
        reasons=[
            DecayReason(
                kind="failed_claim",
                detail="claim failed verification",
                claim_id=claim_id,
                crux_id=crux_id,
            ),
        ],
        recommended_action="repair_required",
    )


@pytest.fixture(autouse=True)
def _enable_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARAGORA_REPAIR_PIPELINE_ENABLED", "1")


# ---------------------------------------------------------------------------
# report_only → None
# ---------------------------------------------------------------------------


class TestReportOnlyReturnsNone:
    def test_report_only_produces_no_proposal(self) -> None:
        spec = propose_repair(_signal(), repair_kind="report_only")
        assert propose_followup_for_repair_spec(spec) is None

    def test_extra_labels_ignored_for_report_only(self) -> None:
        spec = propose_repair(_signal(), repair_kind="report_only")
        assert propose_followup_for_repair_spec(spec, extra_labels=("p1",)) is None


# ---------------------------------------------------------------------------
# shadow_candidate and pr_candidate → FollowupProposal
# ---------------------------------------------------------------------------


class TestProposalShape:
    @pytest.mark.parametrize("kind", ["shadow_candidate", "pr_candidate"])
    def test_returns_proposal(self, kind: str) -> None:
        spec = propose_repair(_signal(), repair_kind=kind)  # type: ignore[arg-type]
        proposal = propose_followup_for_repair_spec(spec)
        assert isinstance(proposal, FollowupProposal)

    @pytest.mark.parametrize("kind", ["shadow_candidate", "pr_candidate"])
    def test_source_kind_is_repair_spec(self, kind: str) -> None:
        spec = propose_repair(_signal(), repair_kind=kind)  # type: ignore[arg-type]
        proposal = propose_followup_for_repair_spec(spec)
        assert proposal is not None
        assert proposal.source_kind == "repair_spec"

    @pytest.mark.parametrize("kind", ["shadow_candidate", "pr_candidate"])
    def test_title_contains_code_unit_id_and_kind(self, kind: str) -> None:
        signal = _signal(code_unit_id="my.code.unit")
        spec = propose_repair(signal, repair_kind=kind)  # type: ignore[arg-type]
        proposal = propose_followup_for_repair_spec(spec)
        assert proposal is not None
        assert "my.code.unit" in proposal.title
        assert kind in proposal.title

    @pytest.mark.parametrize("kind", ["shadow_candidate", "pr_candidate"])
    def test_body_contains_spec_id(self, kind: str) -> None:
        spec = propose_repair(_signal(), repair_kind=kind)  # type: ignore[arg-type]
        proposal = propose_followup_for_repair_spec(spec)
        assert proposal is not None
        assert spec.spec_id in proposal.body

    @pytest.mark.parametrize("kind", ["shadow_candidate", "pr_candidate"])
    def test_body_contains_provenance_hash(self, kind: str) -> None:
        spec = propose_repair(_signal(), repair_kind=kind)  # type: ignore[arg-type]
        proposal = propose_followup_for_repair_spec(spec)
        assert proposal is not None
        assert spec.provenance_hash in proposal.body
        assert len(spec.provenance_hash) == 64  # SHA-256 hex

    @pytest.mark.parametrize("kind", ["shadow_candidate", "pr_candidate"])
    def test_linked_claims_in_body(self, kind: str) -> None:
        spec = propose_repair(
            _signal(claim_id="claim.a"),
            repair_kind=kind,  # type: ignore[arg-type]
            linked_claims=["claim.a", "claim.b"],
        )
        proposal = propose_followup_for_repair_spec(spec)
        assert proposal is not None
        assert "claim.a" in proposal.body
        assert "claim.b" in proposal.body

    @pytest.mark.parametrize("kind", ["shadow_candidate", "pr_candidate"])
    def test_validation_commands_in_body(self, kind: str) -> None:
        spec = propose_repair(
            _signal(),
            repair_kind=kind,  # type: ignore[arg-type]
            validation_commands=["pytest tests/unit.py -q"],
        )
        proposal = propose_followup_for_repair_spec(spec)
        assert proposal is not None
        assert "pytest tests/unit.py -q" in proposal.body


# ---------------------------------------------------------------------------
# Queue-governance invariants
# ---------------------------------------------------------------------------


class TestQueueGovernance:
    @pytest.mark.parametrize("kind", ["shadow_candidate", "pr_candidate"])
    def test_boss_ready_never_in_labels(self, kind: str) -> None:
        spec = propose_repair(_signal(), repair_kind=kind)  # type: ignore[arg-type]
        proposal = propose_followup_for_repair_spec(spec, extra_labels=("boss-ready",))
        assert proposal is not None
        assert "boss-ready" not in proposal.labels

    @pytest.mark.parametrize("kind", ["shadow_candidate", "pr_candidate"])
    def test_epistemic_label_always_present(self, kind: str) -> None:
        spec = propose_repair(_signal(), repair_kind=kind)  # type: ignore[arg-type]
        proposal = propose_followup_for_repair_spec(spec)
        assert proposal is not None
        assert "epistemic" in proposal.labels

    @pytest.mark.parametrize("kind", ["shadow_candidate", "pr_candidate"])
    def test_repair_required_label_always_present(self, kind: str) -> None:
        spec = propose_repair(_signal(), repair_kind=kind)  # type: ignore[arg-type]
        proposal = propose_followup_for_repair_spec(spec)
        assert proposal is not None
        assert "repair-required" in proposal.labels

    @pytest.mark.parametrize("kind", ["shadow_candidate", "pr_candidate"])
    def test_repair_kind_as_label(self, kind: str) -> None:
        spec = propose_repair(_signal(), repair_kind=kind)  # type: ignore[arg-type]
        proposal = propose_followup_for_repair_spec(spec)
        assert proposal is not None
        assert kind in proposal.labels

    @pytest.mark.parametrize("kind", ["shadow_candidate", "pr_candidate"])
    def test_queue_policy_in_body(self, kind: str) -> None:
        spec = propose_repair(_signal(), repair_kind=kind)  # type: ignore[arg-type]
        proposal = propose_followup_for_repair_spec(spec)
        assert proposal is not None
        assert "boss-ready" in proposal.body
        assert "MUST NOT" in proposal.body

    def test_followup_proposal_rejects_boss_ready_in_direct_construction(self) -> None:
        with pytest.raises(ValueError, match="boss-ready"):
            FollowupProposal(
                source_kind="repair_spec",
                source_key="repair_spec_abc123",
                title="test",
                body="test body",
                labels=("boss-ready",),
                rationale="test",
            )


# ---------------------------------------------------------------------------
# Provenance and deduplication
# ---------------------------------------------------------------------------


class TestProvenanceAndDedup:
    @pytest.mark.parametrize("kind", ["shadow_candidate", "pr_candidate"])
    def test_provenance_has_required_fields(self, kind: str) -> None:
        spec = propose_repair(_signal(), repair_kind=kind)  # type: ignore[arg-type]
        proposal = propose_followup_for_repair_spec(spec)
        assert proposal is not None
        prov = proposal.provenance
        assert prov["spec_id"] == spec.spec_id
        assert prov["code_unit_id"] == spec.code_unit_id
        assert prov["repair_kind"] == spec.repair_kind
        assert prov["provenance_hash"] == spec.provenance_hash

    @pytest.mark.parametrize("kind", ["shadow_candidate", "pr_candidate"])
    def test_source_key_deterministic_for_same_spec(self, kind: str) -> None:
        spec = propose_repair(_signal(), repair_kind=kind)  # type: ignore[arg-type]
        p1 = propose_followup_for_repair_spec(spec)
        p2 = propose_followup_for_repair_spec(spec)
        assert p1 is not None and p2 is not None
        assert p1.source_key == p2.source_key

    def test_different_specs_produce_different_source_keys(self) -> None:
        spec_a = propose_repair(_signal(code_unit_id="unit.a"), repair_kind="shadow_candidate")
        spec_b = propose_repair(_signal(code_unit_id="unit.b"), repair_kind="shadow_candidate")
        p_a = propose_followup_for_repair_spec(spec_a)
        p_b = propose_followup_for_repair_spec(spec_b)
        assert p_a is not None and p_b is not None
        assert p_a.source_key != p_b.source_key

    @pytest.mark.parametrize("kind", ["shadow_candidate", "pr_candidate"])
    def test_extra_labels_appear_in_labels(self, kind: str) -> None:
        spec = propose_repair(_signal(), repair_kind=kind)  # type: ignore[arg-type]
        proposal = propose_followup_for_repair_spec(spec, extra_labels=("p1", "needs-review"))
        assert proposal is not None
        assert "p1" in proposal.labels
        assert "needs-review" in proposal.labels
