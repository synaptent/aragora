"""DIC-27 arbitration rows in the DIC-18 truth map.

Verifies that build_truth_map surfaces DIC-27 CruxArbitration objects as
ArbitrationRow entries (with age in days) under ARAGORA_CRUX_ARBITRATION_ENABLED.

Gating:
- Flag OFF (default): arbitration_inputs silently ignored; no rows, count=0.
- Flag ON: rows built from supplied CruxArbitration objects; age is non-negative.

No queue mutations, no boss-ready labels. Advances issue #6221 (DIC-27).
"""

from __future__ import annotations

import pytest

from aragora.epistemic.arbitration import (
    PERSISTENT_CRUX_MIN_CONSECUTIVE,
    PERSISTENT_CRUX_MIN_SCORE,
    PersistentCrux,
    build_arbitration,
)
from aragora.epistemic.claim_verifier import ClaimResult, ClaimStatus
from aragora.epistemic.truth_map import ArbitrationRow, build_truth_map

_CRUX_A = PersistentCrux(
    crux_id="crux_test_001",
    statement="Three consecutive green soaks required before widening B2.",
    question_family_id="qfam_b2_expansion",
    consecutive_debate_count=PERSISTENT_CRUX_MIN_CONSECUTIVE,
    load_bearing_score=PERSISTENT_CRUX_MIN_SCORE,
    cruxset_receipt_ids=("rcpt_a", "rcpt_b", "rcpt_c"),
)

_CRUX_B = PersistentCrux(
    crux_id="crux_test_002",
    statement="Embedding quality determines retrieval accuracy.",
    question_family_id="qfam_retrieval",
    consecutive_debate_count=5,
    load_bearing_score=0.85,
    cruxset_receipt_ids=("rcpt_x",),
)


def _arb(crux=_CRUX_A, **kw):
    kw.setdefault("operator", "alice")
    kw.setdefault("side", "accept")
    kw.setdefault("rationale", "Soaks confirm the claim.")
    return build_arbitration(crux, **kw)


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv("ARAGORA_CRUX_ARBITRATION_ENABLED", "1")


# ---------------------------------------------------------------------------
# Flag-OFF: arbitration_inputs silently ignored
# ---------------------------------------------------------------------------


class TestFlagOff:
    def test_no_rows_when_flag_unset(self, monkeypatch):
        monkeypatch.delenv("ARAGORA_CRUX_ARBITRATION_ENABLED", raising=False)
        report = build_truth_map(claim_results=[], arbitration_inputs=[_arb()])
        assert report.arbitrations == []
        assert report.active_arbitration_count == 0

    def test_to_dict_excludes_arbitrations_key(self, monkeypatch):
        monkeypatch.delenv("ARAGORA_CRUX_ARBITRATION_ENABLED", raising=False)
        d = build_truth_map(claim_results=[], arbitration_inputs=[_arb()]).to_dict()
        assert "arbitrations" not in d
        assert "active_arbitrations" not in d["summary"]

    def test_none_inputs_produces_no_rows_flag_on(self, flag_on):
        report = build_truth_map(claim_results=[], arbitration_inputs=None)
        assert report.arbitrations == []
        assert report.active_arbitration_count == 0


# ---------------------------------------------------------------------------
# Flag-ON: ArbitrationRow populated correctly
# ---------------------------------------------------------------------------


class TestFlagOn:
    def test_single_arb_one_row(self, flag_on):
        report = build_truth_map(claim_results=[], arbitration_inputs=[_arb()])
        assert len(report.arbitrations) == 1

    def test_row_fields_match_arbitration(self, flag_on):
        arb = _arb(operator="carol", side="reject", rationale="Not supported.")
        row = build_truth_map(claim_results=[], arbitration_inputs=[arb]).arbitrations[0]
        assert row.arbitration_id == arb.arbitration_id
        assert row.crux_id == _CRUX_A.crux_id
        assert row.question_family_id == _CRUX_A.question_family_id
        assert row.operator == "carol"
        assert row.side == "reject"
        assert row.created_at == arb.created_at
        assert row.expires_at == arb.expires_at

    def test_age_days_non_negative(self, flag_on):
        row = build_truth_map(claim_results=[], arbitration_inputs=[_arb()]).arbitrations[0]
        assert row.age_days >= 0.0

    def test_fresh_arb_not_expired_not_reversed(self, flag_on):
        row = build_truth_map(claim_results=[], arbitration_inputs=[_arb()]).arbitrations[0]
        assert row.is_expired is False
        assert row.is_reversed is False

    def test_multiple_arbs_multiple_rows(self, flag_on):
        arb1 = _arb(_CRUX_A, side="accept", rationale="R1")
        arb2 = _arb(_CRUX_B, operator="bob", side="defer", rationale="R2")
        report = build_truth_map(claim_results=[], arbitration_inputs=[arb1, arb2])
        assert len(report.arbitrations) == 2
        crux_ids = {r.crux_id for r in report.arbitrations}
        assert crux_ids == {"crux_test_001", "crux_test_002"}

    def test_active_count_counts_non_expired_non_reversed(self, flag_on):
        report = build_truth_map(claim_results=[], arbitration_inputs=[_arb()])
        assert report.active_arbitration_count == 1

    def test_to_dict_includes_arbitrations_and_summary_key(self, flag_on):
        d = build_truth_map(claim_results=[], arbitration_inputs=[_arb()]).to_dict()
        assert "arbitrations" in d
        assert len(d["arbitrations"]) == 1
        assert d["summary"]["active_arbitrations"] == 1

    def test_serialization_stable_when_flag_disabled_after_build(self, flag_on, monkeypatch):
        report = build_truth_map(claim_results=[], arbitration_inputs=[_arb()])
        before = report.to_dict()

        monkeypatch.delenv("ARAGORA_CRUX_ARBITRATION_ENABLED", raising=False)

        assert report.to_dict() == before

    def test_empty_inputs_zero_count(self, flag_on):
        d = build_truth_map(claim_results=[], arbitration_inputs=[]).to_dict()
        assert "arbitrations" not in d
        assert d["summary"]["active_arbitrations"] == 0

    def test_claims_and_arbs_coexist(self, flag_on):
        results = [ClaimResult(claim_id="c1", status=ClaimStatus.PASS, message="", detail={})]
        report = build_truth_map(claim_results=results, arbitration_inputs=[_arb()])
        assert report.total_claims == 1
        assert len(report.arbitrations) == 1

    def test_row_to_dict_has_all_keys(self, flag_on):
        row = build_truth_map(claim_results=[], arbitration_inputs=[_arb()]).arbitrations[0]
        d = row.to_dict()
        expected = {
            "arbitration_id",
            "crux_id",
            "question_family_id",
            "statement",
            "operator",
            "side",
            "created_at",
            "expires_at",
            "age_days",
            "is_expired",
            "is_reversed",
        }
        assert expected == set(d.keys())


def test_serialization_stable_when_flag_enabled_after_build(monkeypatch):
    monkeypatch.delenv("ARAGORA_CRUX_ARBITRATION_ENABLED", raising=False)
    report = build_truth_map(claim_results=[], arbitration_inputs=[_arb()])
    before = report.to_dict()

    monkeypatch.setenv("ARAGORA_CRUX_ARBITRATION_ENABLED", "1")

    assert report.to_dict() == before
