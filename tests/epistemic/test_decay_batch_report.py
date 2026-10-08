"""Tests for EpistemicDecayBatchReport and evaluate_units (DIC-20 / #6031).

Covers the batch evaluation path added to aragora.epistemic.decay_monitor:
- evaluate_units() aggregates per-unit DecaySignal objects into a report
- EpistemicDecayBatchReport.to_dict() produces machine-readable output
- Counts (healthy / degraded / fail_closed) partition total correctly
- Flag: ARAGORA_DECAY_MONITOR_ENABLED (same as CLI); dataclass always importable
"""

from __future__ import annotations

import aragora.epistemic as ep
from aragora.epistemic.claim_verifier import ClaimResult, ClaimStatus
from aragora.epistemic.decay_monitor import (
    EpistemicDecayBatchReport,
    evaluate_units,
)
from aragora.epistemic.proof_unit import DecayPolicy, FallbackPolicy, ProofCarryingCodeUnit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _unit(
    uid: str,
    claims: list[str] | None = None,
    receipts: list[str] | None = None,
    crux_ids: list[str] | None = None,
    failed_claim_policy: str = "report_only",
) -> ProofCarryingCodeUnit:
    return ProofCarryingCodeUnit(
        code_unit_id=uid,
        symbol=f"tests.batch.{uid}",
        source_path=f"tests/{uid}.py",
        owner="test-batch",
        decision_receipts=receipts if receipts is not None else [f"r-{uid}"],
        claims=claims or [],
        assumptions=[],
        verifiers=[],
        freshness_sla_hours=24,
        decay_policy=DecayPolicy(failed_claim=failed_claim_policy),
        fallback_policy=FallbackPolicy(),
        linked_crux_ids=crux_ids or [],
    )


def _fail(claim_id: str) -> ClaimResult:
    return ClaimResult(claim_id=claim_id, status=ClaimStatus.FAIL, message="test-fail")


def _stale(claim_id: str) -> ClaimResult:
    return ClaimResult(claim_id=claim_id, status=ClaimStatus.STALE, message="test-stale")


# ---------------------------------------------------------------------------
# evaluate_units — basic behaviour
# ---------------------------------------------------------------------------


class TestEvaluateUnitsBasic:
    def test_empty_units_returns_empty_report(self):
        report = evaluate_units([])
        assert report.total == 0
        assert report.healthy_count == 0
        assert report.degraded_count == 0
        assert report.fail_closed_count == 0

    def test_returns_epistemic_decay_batch_report(self):
        assert isinstance(evaluate_units([]), EpistemicDecayBatchReport)

    def test_signals_length_equals_total(self):
        units = [_unit("a"), _unit("b"), _unit("c")]
        report = evaluate_units(units)
        assert len(report.signals) == report.total == 3

    def test_all_healthy_units(self):
        units = [_unit("a"), _unit("b")]
        report = evaluate_units(units)
        assert report.healthy_count == 2
        assert report.degraded_count == 0
        assert report.fail_closed_count == 0

    def test_counts_partition_total(self):
        units = [
            _unit("a"),
            _unit("b", receipts=[]),
            _unit("c", claims=["x"], failed_claim_policy="fail_closed"),
        ]
        report = evaluate_units(units, claim_results={"x": _fail("x")})
        assert (
            report.healthy_count + report.degraded_count + report.fail_closed_count == report.total
        )


# ---------------------------------------------------------------------------
# evaluate_units — count semantics
# ---------------------------------------------------------------------------


class TestEvaluateUnitsCounts:
    def test_missing_receipt_lands_in_degraded_not_fail_closed(self):
        report = evaluate_units([_unit("a", receipts=[])])
        assert report.degraded_count == 1
        assert report.fail_closed_count == 0
        assert report.healthy_count == 0

    def test_failed_claim_fail_closed_policy_lands_in_fail_closed(self):
        units = [_unit("a", claims=["c1"], failed_claim_policy="fail_closed")]
        report = evaluate_units(units, claim_results={"c1": _fail("c1")})
        assert report.fail_closed_count == 1
        assert report.degraded_count == 0

    def test_mixed_units_counted_correctly(self):
        units = [
            _unit("healthy"),
            _unit("no-receipt", receipts=[]),
            _unit("fail-closed", claims=["x"], failed_claim_policy="fail_closed"),
            _unit("repair-req", claims=["y"], failed_claim_policy="repair_required"),
        ]
        report = evaluate_units(units, claim_results={"x": _fail("x"), "y": _fail("y")})
        assert report.healthy_count == 1
        assert report.degraded_count == 2  # no-receipt + repair_required
        assert report.fail_closed_count == 1


# ---------------------------------------------------------------------------
# evaluate_units — shared inputs
# ---------------------------------------------------------------------------


class TestEvaluateUnitsSharedInputs:
    def test_shared_claim_results_apply_to_all_units(self):
        units = [_unit("a", claims=["c1"]), _unit("b", claims=["c1"])]
        report = evaluate_units(units, claim_results={"c1": _fail("c1")})
        assert all(s.integrity_score < 1.0 for s in report.signals)

    def test_shared_unresolved_crux_applies_to_linked_units(self):
        units = [_unit("a", crux_ids=["crux.x"]), _unit("b")]
        report = evaluate_units(units, unresolved_crux_ids=frozenset({"crux.x"}))
        assert report.signals[0].integrity_score < 1.0
        assert report.signals[1].integrity_score == 1.0

    def test_generator_input_is_consumed_correctly(self):
        def gen():
            yield _unit("a")
            yield _unit("b")

        report = evaluate_units(gen())
        assert report.total == 2


# ---------------------------------------------------------------------------
# evaluate_units — generated_at
# ---------------------------------------------------------------------------


class TestEvaluateUnitsTimestamp:
    def test_generated_at_is_set_when_not_provided(self):
        report = evaluate_units([])
        assert report.generated_at != ""

    def test_generated_at_respects_override(self):
        ts = "2026-07-22T00:00:00+00:00"
        report = evaluate_units([], generated_at=ts)
        assert report.generated_at == ts

    def test_generated_at_in_dict(self):
        ts = "2026-07-22T00:00:00+00:00"
        d = evaluate_units([], generated_at=ts).to_dict()
        assert d["generated_at"] == ts


# ---------------------------------------------------------------------------
# EpistemicDecayBatchReport.to_dict
# ---------------------------------------------------------------------------


class TestEpistemicDecayBatchReportToDict:
    def test_required_keys_present(self):
        d = evaluate_units([]).to_dict()
        assert set(d) >= {
            "generated_at",
            "total",
            "healthy_count",
            "degraded_count",
            "fail_closed_count",
            "signals",
        }

    def test_counts_in_dict_are_consistent(self):
        units = [
            _unit("a"),
            _unit("b", receipts=[]),
            _unit("c", claims=["z"], failed_claim_policy="fail_closed"),
        ]
        d = evaluate_units(units, claim_results={"z": _fail("z")}).to_dict()
        assert d["total"] == 3
        assert d["healthy_count"] == 1
        assert d["degraded_count"] == 1
        assert d["fail_closed_count"] == 1

    def test_empty_report_dict_has_zero_counts(self):
        d = evaluate_units([]).to_dict()
        assert (
            d["total"] == d["healthy_count"] == d["degraded_count"] == d["fail_closed_count"] == 0
        )


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


class TestPublicSurface:
    def test_evaluate_units_exported_from_aragora_epistemic(self):
        assert hasattr(ep, "evaluate_units")
        assert "evaluate_units" in ep.__all__

    def test_epistemic_decay_batch_report_exported_from_aragora_epistemic(self):
        assert hasattr(ep, "EpistemicDecayBatchReport")
        assert "EpistemicDecayBatchReport" in ep.__all__

    def test_dataclass_importable_without_flag(self):
        from aragora.epistemic.decay_monitor import EpistemicDecayBatchReport as R

        assert R is not None
