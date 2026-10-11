"""Tests for viah_decay_signals — DIC-20 EpistemicDecayBatchReport → AGT-06 VIAH bridge.

Verifies count_failed_claims_from_decay with synthetic DecaySignal fixtures:
flag gate, reason-kind filtering, recommended_action threshold, and multi-unit batches.
"""

from __future__ import annotations

import pytest

from aragora.epistemic.decay_monitor import (
    DecayReason,
    DecaySignal,
    EpistemicDecayBatchReport,
)
from aragora.evaluation.viah_decay_signals import count_failed_claims_from_decay


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _reason(kind: str, detail: str = "") -> DecayReason:
    return DecayReason(kind=kind, detail=detail or f"synthetic {kind}")


def _signal(
    *,
    recommended_action: str = "report_only",
    reason_kinds: list[str] | None = None,
    code_unit_id: str = "unit.test",
    integrity_score: float = 0.7,
) -> DecaySignal:
    return DecaySignal(
        code_unit_id=code_unit_id,
        integrity_score=integrity_score,
        reasons=[_reason(k) for k in (reason_kinds or [])],
        recommended_action=recommended_action,
    )


def _report(*signals: DecaySignal) -> EpistemicDecayBatchReport:
    return EpistemicDecayBatchReport(
        signals=list(signals),
        generated_at="2026-09-02T00:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# Flag gate
# ---------------------------------------------------------------------------


class TestFlagGate:
    def test_returns_zero_without_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARAGORA_VIAH_TREND_ENABLED", raising=False)
        report = _report(_signal(recommended_action="fail_closed", reason_kinds=["failed_claim"]))
        assert count_failed_claims_from_decay(report) == 0

    def test_counts_when_flag_set_to_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_VIAH_TREND_ENABLED", "1")
        report = _report(_signal(recommended_action="fail_closed", reason_kinds=["failed_claim"]))
        assert count_failed_claims_from_decay(report) == 1

    def test_counts_when_flag_set_to_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_VIAH_TREND_ENABLED", "true")
        report = _report(_signal(recommended_action="fail_closed", reason_kinds=["failed_claim"]))
        assert count_failed_claims_from_decay(report) == 1

    def test_returns_zero_for_empty_string_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_VIAH_TREND_ENABLED", "")
        report = _report(_signal(recommended_action="fail_closed", reason_kinds=["failed_claim"]))
        assert count_failed_claims_from_decay(report) == 0


# ---------------------------------------------------------------------------
# Recommended-action threshold
# ---------------------------------------------------------------------------


class TestRecommendedAction:
    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_VIAH_TREND_ENABLED", "1")

    def test_report_only_not_counted(self) -> None:
        report = _report(_signal(recommended_action="report_only", reason_kinds=["failed_claim"]))
        assert count_failed_claims_from_decay(report) == 0

    def test_repair_required_with_claim_failure_counted(self) -> None:
        report = _report(
            _signal(recommended_action="repair_required", reason_kinds=["failed_claim"])
        )
        assert count_failed_claims_from_decay(report) == 1

    def test_fail_closed_with_claim_failure_counted(self) -> None:
        report = _report(_signal(recommended_action="fail_closed", reason_kinds=["failed_claim"]))
        assert count_failed_claims_from_decay(report) == 1

    def test_fail_closed_with_verifier_error_counted(self) -> None:
        report = _report(_signal(recommended_action="fail_closed", reason_kinds=["verifier_error"]))
        assert count_failed_claims_from_decay(report) == 1


# ---------------------------------------------------------------------------
# Reason-kind filtering
# ---------------------------------------------------------------------------


class TestReasonKindFiltering:
    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_VIAH_TREND_ENABLED", "1")

    def test_stale_evidence_only_excluded(self) -> None:
        report = _report(
            _signal(recommended_action="repair_required", reason_kinds=["stale_evidence"])
        )
        assert count_failed_claims_from_decay(report) == 0

    def test_unresolved_crux_only_excluded(self) -> None:
        report = _report(
            _signal(recommended_action="fail_closed", reason_kinds=["unresolved_crux"])
        )
        assert count_failed_claims_from_decay(report) == 0

    def test_missing_receipt_only_excluded(self) -> None:
        report = _report(
            _signal(recommended_action="fail_closed", reason_kinds=["missing_receipt"])
        )
        assert count_failed_claims_from_decay(report) == 0

    def test_mixed_reasons_counted_when_claim_kind_present(self) -> None:
        report = _report(
            _signal(
                recommended_action="repair_required",
                reason_kinds=["stale_evidence", "failed_claim"],
            )
        )
        assert count_failed_claims_from_decay(report) == 1

    def test_no_reasons_not_counted(self) -> None:
        report = _report(_signal(recommended_action="fail_closed", reason_kinds=[]))
        assert count_failed_claims_from_decay(report) == 0


# ---------------------------------------------------------------------------
# Batch / multi-unit
# ---------------------------------------------------------------------------


class TestBatch:
    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_VIAH_TREND_ENABLED", "1")

    def test_empty_report_returns_zero(self) -> None:
        assert count_failed_claims_from_decay(_report()) == 0

    def test_multiple_units_counted_correctly(self) -> None:
        report = _report(
            _signal(
                code_unit_id="u1",
                recommended_action="fail_closed",
                reason_kinds=["failed_claim"],
            ),
            _signal(
                code_unit_id="u2",
                recommended_action="repair_required",
                reason_kinds=["verifier_error"],
            ),
            _signal(
                code_unit_id="u3",
                recommended_action="report_only",
                reason_kinds=["failed_claim"],
            ),
            _signal(
                code_unit_id="u4",
                recommended_action="fail_closed",
                reason_kinds=["stale_evidence"],
            ),
        )
        assert count_failed_claims_from_decay(report) == 2

    def test_all_healthy_returns_zero(self) -> None:
        report = _report(
            _signal(code_unit_id="u1", recommended_action="report_only", reason_kinds=[]),
            _signal(code_unit_id="u2", recommended_action="report_only", reason_kinds=[]),
        )
        assert count_failed_claims_from_decay(report) == 0

    def test_all_actionable_claim_failures_counted(self) -> None:
        report = _report(
            *[
                _signal(
                    code_unit_id=f"u{i}",
                    recommended_action="fail_closed",
                    reason_kinds=["failed_claim"],
                )
                for i in range(5)
            ]
        )
        assert count_failed_claims_from_decay(report) == 5
