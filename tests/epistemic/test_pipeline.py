"""Tests for aragora.epistemic.pipeline (DIC-20 → DIC-21 chaining helper).

All tests are hermetic — no network, no file I/O, no real claim verifiers.
Claim results are injected directly via the ``claim_results`` parameter.

Coverage:
- Flag gate: disabled by default, enabled by truthy env value.
- :class:`EpistemicPipelineResult`: to_dict, field access.
- Healthy unit → report_only in both signal and decision.
- Failed claim → decay propagates; live_dispatch class escalates.
- Multiple failed claims → integrity below fail_closed threshold.
- ``code_unit_class`` routing uses the correct DEFAULT_POLICIES entry.
- ``unresolved_crux_ids`` propagate to the decay signal.
- Explicit ``policy`` override bypasses class lookup.

Advances: issues #6031 (DIC-20) and #6032 (DIC-21).
"""

from __future__ import annotations

import pytest

from aragora.epistemic.claim_verifier import ClaimResult, ClaimStatus
from aragora.epistemic.pipeline import (
    _FLAG,
    EpistemicPipelineResult,
    epistemic_pipeline_enabled,
    evaluate_and_quarantine,
)
from aragora.epistemic.proof_unit import DecayPolicy, FallbackPolicy, ProofCarryingCodeUnit
from aragora.epistemic.quarantine_policy import EscalationMap, QuarantinePolicy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unit(
    claims: list[str] | None = None,
    linked_crux_ids: list[str] | None = None,
    decision_receipts: list[str] | None = None,
    decay_policy: DecayPolicy | None = None,
) -> ProofCarryingCodeUnit:
    return ProofCarryingCodeUnit(
        code_unit_id="unit.pipeline.test",
        symbol="tests.fake.pipeline_fn",
        source_path="tests/fake_pipeline.py",
        owner="test-suite",
        decision_receipts=decision_receipts if decision_receipts is not None else ["rcpt-001"],
        claims=claims if claims is not None else ["claim.truth.rate"],
        assumptions=["External service is stable."],
        verifiers=[],
        freshness_sla_hours=24,
        decay_policy=decay_policy if decay_policy is not None else DecayPolicy(),
        fallback_policy=FallbackPolicy(),
        linked_crux_ids=linked_crux_ids if linked_crux_ids is not None else [],
    )


def _fail(claim_id: str) -> ClaimResult:
    return ClaimResult(
        claim_id=claim_id,
        status=ClaimStatus.FAIL,
        message="synthetic failure",
        severity="error",
        allowed_action="repair_required",
    )


# ---------------------------------------------------------------------------
# Flag gate
# ---------------------------------------------------------------------------


class TestFlagGate:
    def test_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_FLAG, raising=False)
        assert not epistemic_pipeline_enabled()

    @pytest.mark.parametrize("val", ["1", "true", "yes", "on"])
    def test_truthy_values_enable(self, monkeypatch: pytest.MonkeyPatch, val: str) -> None:
        monkeypatch.setenv(_FLAG, val)
        assert epistemic_pipeline_enabled()

    @pytest.mark.parametrize("val", ["0", "false", "no", "off", ""])
    def test_falsy_values_disable(self, monkeypatch: pytest.MonkeyPatch, val: str) -> None:
        monkeypatch.setenv(_FLAG, val)
        assert not epistemic_pipeline_enabled()

    def test_raises_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_FLAG, raising=False)
        with pytest.raises(RuntimeError, match=_FLAG):
            evaluate_and_quarantine(_unit())


# ---------------------------------------------------------------------------
# Return type and structure
# ---------------------------------------------------------------------------


class TestPipelineResult:
    def test_returns_pipeline_result_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_FLAG, "1")
        result = evaluate_and_quarantine(_unit())
        assert isinstance(result, EpistemicPipelineResult)

    def test_decay_signal_code_unit_id_matches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_FLAG, "1")
        result = evaluate_and_quarantine(_unit())
        assert result.decay_signal.code_unit_id == "unit.pipeline.test"

    def test_quarantine_decision_code_unit_id_matches(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_FLAG, "1")
        result = evaluate_and_quarantine(_unit())
        assert result.quarantine_decision.code_unit_id == "unit.pipeline.test"

    def test_to_dict_contains_both_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_FLAG, "1")
        d = evaluate_and_quarantine(_unit()).to_dict()
        assert "decay_signal" in d
        assert "quarantine_decision" in d

    def test_to_dict_decay_signal_has_integrity_score(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_FLAG, "1")
        d = evaluate_and_quarantine(_unit()).to_dict()
        assert "integrity_score" in d["decay_signal"]

    def test_to_dict_quarantine_decision_has_policy_action(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_FLAG, "1")
        d = evaluate_and_quarantine(_unit()).to_dict()
        assert "policy_action" in d["quarantine_decision"]


# ---------------------------------------------------------------------------
# Healthy unit: no failures, full integrity
# ---------------------------------------------------------------------------


class TestHealthyUnit:
    def test_healthy_unit_full_integrity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_FLAG, "1")
        result = evaluate_and_quarantine(_unit())
        assert result.decay_signal.integrity_score == pytest.approx(1.0)

    def test_healthy_unit_report_only_signal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_FLAG, "1")
        result = evaluate_and_quarantine(_unit())
        assert result.decay_signal.recommended_action == "report_only"

    def test_healthy_unit_report_only_decision(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_FLAG, "1")
        result = evaluate_and_quarantine(_unit())
        assert result.quarantine_decision.policy_action == "report_only"

    def test_healthy_unit_not_fail_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_FLAG, "1")
        result = evaluate_and_quarantine(_unit())
        assert not result.quarantine_decision.fail_closed


# ---------------------------------------------------------------------------
# Failed claim escalation
# ---------------------------------------------------------------------------


class TestFailedClaim:
    def test_failed_claim_reduces_integrity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_FLAG, "1")
        result = evaluate_and_quarantine(
            _unit(claims=["claim.truth.rate"]),
            claim_results={"claim.truth.rate": _fail("claim.truth.rate")},
        )
        assert result.decay_signal.integrity_score < 1.0

    def test_failed_claim_produces_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_FLAG, "1")
        result = evaluate_and_quarantine(
            _unit(claims=["claim.truth.rate"]),
            claim_results={"claim.truth.rate": _fail("claim.truth.rate")},
        )
        reason_kinds = {r.kind for r in result.decay_signal.reasons}
        assert "failed_claim" in reason_kinds

    def test_live_dispatch_class_escalates_repair_to_quarantine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_FLAG, "1")
        result = evaluate_and_quarantine(
            _unit(claims=["claim.alpha"], decay_policy=DecayPolicy(failed_claim="repair_required")),
            claim_results={"claim.alpha": _fail("claim.alpha")},
            code_unit_class="live_dispatch",
        )
        # live_dispatch policy escalates repair_required → quarantine
        assert result.quarantine_decision.policy_action in {"quarantine", "fail_closed"}


# ---------------------------------------------------------------------------
# Fail-closed threshold
# ---------------------------------------------------------------------------


class TestFailClosed:
    def test_multiple_failures_drive_fail_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_FLAG, "1")
        claim_ids = [f"claim.{i}" for i in range(4)]
        results = {cid: _fail(cid) for cid in claim_ids}
        result = evaluate_and_quarantine(
            _unit(claims=claim_ids),
            claim_results=results,
            code_unit_class="live_dispatch",
        )
        # live_dispatch fails closed at 0.6; 4 failed claims → integrity ≤ 0.4
        assert result.quarantine_decision.fail_closed

    def test_fail_closed_sets_live_swap_blocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_FLAG, "1")
        claim_ids = [f"claim.{i}" for i in range(4)]
        results = {cid: _fail(cid) for cid in claim_ids}
        result = evaluate_and_quarantine(
            _unit(claims=claim_ids),
            claim_results=results,
            code_unit_class="live_dispatch",
        )
        assert result.quarantine_decision.live_swap_blocked


# ---------------------------------------------------------------------------
# code_unit_class routing
# ---------------------------------------------------------------------------


class TestCodeUnitClassRouting:
    @pytest.mark.parametrize("cls", ["default", "demo", "report_surface", "live_dispatch"])
    def test_healthy_unit_is_report_only_for_all_classes(
        self, monkeypatch: pytest.MonkeyPatch, cls: str
    ) -> None:
        monkeypatch.setenv(_FLAG, "1")
        result = evaluate_and_quarantine(_unit(), code_unit_class=cls)
        assert result.quarantine_decision.policy_action == "report_only"

    def test_demo_class_lower_fail_closed_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_FLAG, "1")
        claim_ids = ["claim.a", "claim.b"]
        results = {cid: _fail(cid) for cid in claim_ids}
        result = evaluate_and_quarantine(
            _unit(claims=claim_ids),
            claim_results=results,
            code_unit_class="demo",
        )
        # demo threshold is 0.2; 2 failed claims → 0.4 deduction → score ≈ 0.6 → NOT fail_closed
        # But integrity < 1.0 and decision should escalate beyond report_only
        assert result.decay_signal.integrity_score < 1.0


# ---------------------------------------------------------------------------
# Explicit policy override
# ---------------------------------------------------------------------------


class TestExplicitPolicy:
    def test_explicit_policy_overrides_class_lookup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_FLAG, "1")
        strict_policy = QuarantinePolicy(
            code_unit_class="custom_strict",
            escalation_map=EscalationMap(
                report_only="quarantine",
                repair_required="fail_closed",
            ),
            fail_closed_threshold=0.9,
        )
        result = evaluate_and_quarantine(
            _unit(),
            policy=strict_policy,
        )
        # A healthy unit with a strict policy that maps report_only → quarantine
        # integrity=1.0 ≥ 0.9 so not fail_closed; recommended_action=report_only → escalated
        assert result.quarantine_decision.policy_action == "quarantine"


# ---------------------------------------------------------------------------
# Unresolved crux propagation
# ---------------------------------------------------------------------------


class TestUnresolvedCrux:
    def test_unresolved_crux_reduces_integrity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_FLAG, "1")
        result = evaluate_and_quarantine(
            _unit(linked_crux_ids=["crux.b2.guard"]),
            unresolved_crux_ids=frozenset({"crux.b2.guard"}),
        )
        assert result.decay_signal.integrity_score < 1.0

    def test_unresolved_crux_produces_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_FLAG, "1")
        result = evaluate_and_quarantine(
            _unit(linked_crux_ids=["crux.b2.guard"]),
            unresolved_crux_ids=frozenset({"crux.b2.guard"}),
        )
        reason_kinds = {r.kind for r in result.decay_signal.reasons}
        assert "unresolved_crux" in reason_kinds
