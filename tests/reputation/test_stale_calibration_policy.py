"""Tests for the three-axis stale-calibration policy (AGT-05 / #6066).

Policy table under test
-----------------------
| Condition                           | Decision          | Modifier |
|-------------------------------------|-------------------|----------|
| evidence_age < 0.5 × half_life      | decay_penalty     | 1.0      |
| 0.5 × hl ≤ evidence_age < 1.5 × hl | renewal_required  | 0.0      |
| evidence_age ≥ 1.5 × half_life      | abstain           | 0.0      |

Reference: docs/plans/2026-04-29-agt-05-stale-claim-policy.md
"""

from __future__ import annotations

import pytest

from aragora.reputation.stale_policy import (
    PolicyDecision,
    StaleCalibrationDecision,
    resolve_stale_calibration,
)

HL = 30.0  # days — mirrors settlement default
LO = 0.5 * HL  # 15.0 — lower band boundary
HI = 1.5 * HL  # 45.0 — upper band boundary


# ---------------------------------------------------------------------------
# Band routing
# ---------------------------------------------------------------------------


class TestBandRouting:
    @pytest.mark.parametrize("age", [0.0, 5.0, LO - 0.001])
    def test_penalty_band(self, age: float) -> None:
        d = resolve_stale_calibration(evidence_age_days=age, half_life_days=HL)
        assert d.policy_decision == PolicyDecision.DECAY_PENALTY
        assert d.calibration_delta_modifier == 1.0
        assert d.claim_renewal_id is None

    @pytest.mark.parametrize("age", [LO, HL, HI - 0.001])
    def test_renewal_band(self, age: float) -> None:
        d = resolve_stale_calibration(evidence_age_days=age, half_life_days=HL)
        assert d.policy_decision == PolicyDecision.RENEWAL_REQUIRED
        assert d.calibration_delta_modifier == 0.0
        assert d.claim_renewal_id is not None
        assert d.claim_renewal_id.startswith("renew_")
        assert len(d.claim_renewal_id) == 22  # "renew_" + 16 hex chars

    @pytest.mark.parametrize("age", [HI, HI + 10.0, 365.0])
    def test_abstain_band(self, age: float) -> None:
        d = resolve_stale_calibration(evidence_age_days=age, half_life_days=HL)
        assert d.policy_decision == PolicyDecision.ABSTAIN
        assert d.calibration_delta_modifier == 0.0
        assert d.claim_renewal_id is None


# ---------------------------------------------------------------------------
# Renewal-id determinism
# ---------------------------------------------------------------------------


class TestRenewalIdDeterminism:
    def test_same_inputs_produce_same_id(self) -> None:
        d1 = resolve_stale_calibration(evidence_age_days=20.0, half_life_days=HL, claim_id="c1")
        d2 = resolve_stale_calibration(evidence_age_days=20.0, half_life_days=HL, claim_id="c1")
        assert d1.claim_renewal_id == d2.claim_renewal_id

    def test_different_claim_ids_differ(self) -> None:
        d1 = resolve_stale_calibration(evidence_age_days=20.0, half_life_days=HL, claim_id="c1")
        d2 = resolve_stale_calibration(evidence_age_days=20.0, half_life_days=HL, claim_id="c2")
        assert d1.claim_renewal_id != d2.claim_renewal_id

    def test_empty_claim_id_produces_id(self) -> None:
        d = resolve_stale_calibration(evidence_age_days=20.0, half_life_days=HL)
        assert d.claim_renewal_id is not None


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------


class TestPolicyFingerprint:
    def test_stable_across_calls(self) -> None:
        d1 = resolve_stale_calibration(evidence_age_days=10.0, half_life_days=HL)
        d2 = resolve_stale_calibration(evidence_age_days=10.0, half_life_days=HL)
        assert d1.policy_fingerprint == d2.policy_fingerprint

    def test_changes_with_age(self) -> None:
        d1 = resolve_stale_calibration(evidence_age_days=10.0, half_life_days=HL)
        d2 = resolve_stale_calibration(evidence_age_days=20.0, half_life_days=HL)
        assert d1.policy_fingerprint != d2.policy_fingerprint

    def test_format(self) -> None:
        d = resolve_stale_calibration(evidence_age_days=10.0, half_life_days=HL)
        assert d.policy_fingerprint.startswith("cp_")
        assert len(d.policy_fingerprint) == 15  # "cp_" + 12 hex chars


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_negative_age_raises(self) -> None:
        with pytest.raises(ValueError, match="evidence_age_days"):
            resolve_stale_calibration(evidence_age_days=-0.001, half_life_days=HL)

    def test_zero_half_life_raises(self) -> None:
        with pytest.raises(ValueError, match="half_life_days"):
            resolve_stale_calibration(evidence_age_days=10.0, half_life_days=0.0)

    def test_negative_half_life_raises(self) -> None:
        with pytest.raises(ValueError, match="half_life_days"):
            resolve_stale_calibration(evidence_age_days=10.0, half_life_days=-5.0)


# ---------------------------------------------------------------------------
# Metadata preservation and return type
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_evidence_age_preserved(self) -> None:
        d = resolve_stale_calibration(evidence_age_days=12.3, half_life_days=HL)
        assert d.evidence_age_days == 12.3

    def test_half_life_preserved(self) -> None:
        d = resolve_stale_calibration(evidence_age_days=10.0, half_life_days=25.0)
        assert d.half_life_used_days == 25.0

    def test_return_type(self) -> None:
        d = resolve_stale_calibration(evidence_age_days=5.0, half_life_days=HL)
        assert isinstance(d, StaleCalibrationDecision)

    def test_modifier_is_binary(self) -> None:
        for age in [1.0, LO, HL, HI, 200.0]:
            d = resolve_stale_calibration(evidence_age_days=age, half_life_days=HL)
            assert d.calibration_delta_modifier in (0.0, 1.0)


# ---------------------------------------------------------------------------
# Scales correctly with custom half_life
# ---------------------------------------------------------------------------


class TestCustomHalfLife:
    HL2 = 10.0

    def test_penalty_below_lo(self) -> None:
        d = resolve_stale_calibration(evidence_age_days=4.0, half_life_days=self.HL2)
        assert d.policy_decision == PolicyDecision.DECAY_PENALTY

    def test_renewal_at_lo(self) -> None:
        d = resolve_stale_calibration(evidence_age_days=5.0, half_life_days=self.HL2)
        assert d.policy_decision == PolicyDecision.RENEWAL_REQUIRED

    def test_abstain_at_hi(self) -> None:
        d = resolve_stale_calibration(evidence_age_days=15.0, half_life_days=self.HL2)
        assert d.policy_decision == PolicyDecision.ABSTAIN
