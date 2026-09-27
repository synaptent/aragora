from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal
import json

import pytest

from aragora.evaluation.outcome_backed_budget import (
    BUDGET_LEDGER_SCHEMA,
    BudgetLedgerError,
    DailyBudgetExceededError,
    OutcomeBackedBudgetLedger,
)


DAY_ONE = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
DAY_TWO = datetime(2026, 8, 31, 1, tzinfo=timezone.utc)


def _reserve(
    ledger: OutcomeBackedBudgetLedger,
    reservation_id: str,
    amount: object,
    *,
    logical_call_id: str | None = None,
    attempt: int = 1,
    at: datetime = DAY_ONE,
) -> dict[str, object]:
    return ledger.reserve(
        reservation_id=reservation_id,
        logical_call_id=logical_call_id or reservation_id,
        run_id="development-run-1",
        case_id="software-development-01",
        condition_id="claude-single",
        attempt=attempt,
        estimated_cost_usd=amount,
        recorded_at=at,
    )


def test_empty_snapshot_has_full_daily_budget(tmp_path) -> None:
    ledger = OutcomeBackedBudgetLedger(tmp_path / "costs.jsonl")

    snapshot = ledger.snapshot(utc_date=DAY_ONE.date())

    assert snapshot.to_dict() == {
        "utc_date": "2026-08-30",
        "cap_usd": "25",
        "settled_usd": "0",
        "reserved_usd": "0",
        "committed_usd": "0",
        "remaining_usd": "25",
        "open_reservations": 0,
        "event_count": 0,
        "exceeded": False,
    }


def test_reservation_then_settlement_replaces_estimate_with_actual(tmp_path) -> None:
    path = tmp_path / "costs.jsonl"
    ledger = OutcomeBackedBudgetLedger(path)
    reserved = _reserve(ledger, "call-1-attempt-1", "4.50")

    pending = ledger.snapshot(utc_date=DAY_ONE.date())
    assert pending.reserved_usd == Decimal("4.5")
    assert pending.settled_usd == 0
    assert pending.open_reservations == 1

    settled = ledger.settle(
        "call-1-attempt-1", actual_cost_usd="3.25", outcome="success", recorded_at=DAY_ONE
    )
    snapshot = ledger.snapshot(utc_date=DAY_ONE.date())

    assert reserved["schema_version"] == BUDGET_LEDGER_SCHEMA
    assert settled["actual_cost_usd"] == "3.25"
    assert snapshot.settled_usd == Decimal("3.25")
    assert snapshot.reserved_usd == 0
    assert snapshot.remaining_usd == Decimal("21.75")
    assert snapshot.open_reservations == 0
    assert len(path.read_text().splitlines()) == 2


def test_paid_reservations_cannot_exceed_cap_but_zero_cost_capacity_remains_usable(
    tmp_path,
) -> None:
    ledger = OutcomeBackedBudgetLedger(tmp_path / "costs.jsonl")
    _reserve(ledger, "paid-1", "24.75")

    with pytest.raises(DailyBudgetExceededError, match=r"24\.75.*0\.26.*25"):
        _reserve(ledger, "paid-2", "0.26")

    event = _reserve(ledger, "subscription-1", "0")
    assert event["estimated_cost_usd"] == "0"


def test_exact_cap_is_allowed_and_additional_paid_call_is_blocked(tmp_path) -> None:
    ledger = OutcomeBackedBudgetLedger(tmp_path / "costs.jsonl")
    _reserve(ledger, "call-1", "25")

    assert ledger.snapshot(utc_date=DAY_ONE.date()).remaining_usd == 0
    with pytest.raises(DailyBudgetExceededError):
        _reserve(ledger, "call-2", "0.01")


def test_actual_overshoot_is_recorded_truthfully_and_blocks_more_paid_calls(tmp_path) -> None:
    ledger = OutcomeBackedBudgetLedger(tmp_path / "costs.jsonl")
    _reserve(ledger, "call-1", "20")
    ledger.settle("call-1", actual_cost_usd="26", outcome="success", recorded_at=DAY_ONE)

    snapshot = ledger.snapshot(utc_date=DAY_ONE.date())
    assert snapshot.exceeded is True
    assert snapshot.settled_usd == 26
    with pytest.raises(DailyBudgetExceededError):
        _reserve(ledger, "call-2", "0.01")


def test_one_retry_is_allowed_only_after_infrastructure_failure(tmp_path) -> None:
    ledger = OutcomeBackedBudgetLedger(tmp_path / "costs.jsonl")
    _reserve(ledger, "logical-1-a1", "1", logical_call_id="logical-1")

    with pytest.raises(BudgetLedgerError, match="retry before first attempt settled"):
        _reserve(
            ledger,
            "logical-1-a2-too-early",
            "1",
            logical_call_id="logical-1",
            attempt=2,
        )

    ledger.settle(
        "logical-1-a1",
        actual_cost_usd="0.25",
        outcome="infrastructure_error",
        recorded_at=DAY_ONE,
    )
    retry = _reserve(ledger, "logical-1-a2", "1", logical_call_id="logical-1", attempt=2)
    assert retry["attempt"] == 2

    with pytest.raises(ValueError, match="between 1 and 2"):
        _reserve(ledger, "logical-1-a3", "1", logical_call_id="logical-1", attempt=3)


def test_model_failure_does_not_authorize_retry(tmp_path) -> None:
    ledger = OutcomeBackedBudgetLedger(tmp_path / "costs.jsonl")
    _reserve(ledger, "logical-1-a1", "1", logical_call_id="logical-1")
    ledger.settle(
        "logical-1-a1", actual_cost_usd="0.25", outcome="model_error", recorded_at=DAY_ONE
    )

    with pytest.raises(BudgetLedgerError, match="retry requires infrastructure failure"):
        _reserve(ledger, "logical-1-a2", "1", logical_call_id="logical-1", attempt=2)


def test_reservation_date_controls_budget_when_settlement_crosses_midnight(tmp_path) -> None:
    ledger = OutcomeBackedBudgetLedger(tmp_path / "costs.jsonl")
    _reserve(ledger, "call-1", "2", at=DAY_ONE)
    ledger.settle("call-1", actual_cost_usd="3", outcome="success", recorded_at=DAY_TWO)

    assert ledger.snapshot(utc_date=DAY_ONE.date()).settled_usd == 3
    assert ledger.snapshot(utc_date=DAY_TWO.date()).settled_usd == 0


def test_duplicate_reservation_and_settlement_fail_closed(tmp_path) -> None:
    ledger = OutcomeBackedBudgetLedger(tmp_path / "costs.jsonl")
    _reserve(ledger, "call-1", "1")
    with pytest.raises(BudgetLedgerError, match="duplicate reservation"):
        _reserve(ledger, "call-1", "1")

    ledger.settle("call-1", actual_cost_usd="1", outcome="success", recorded_at=DAY_ONE)
    with pytest.raises(BudgetLedgerError, match="already settled"):
        ledger.settle("call-1", actual_cost_usd="1", outcome="success", recorded_at=DAY_ONE)


def test_tampered_hash_chain_blocks_reads_and_new_admission(tmp_path) -> None:
    path = tmp_path / "costs.jsonl"
    ledger = OutcomeBackedBudgetLedger(path)
    _reserve(ledger, "call-1", "1")
    payload = json.loads(path.read_text())
    payload["estimated_cost_usd"] = "0"
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")

    with pytest.raises(BudgetLedgerError, match="event hash mismatch"):
        ledger.snapshot(utc_date=DAY_ONE.date())
    with pytest.raises(BudgetLedgerError, match="event hash mismatch"):
        _reserve(ledger, "call-2", "1")


@pytest.mark.parametrize("content", ["{}", "not-json\n", "\n"])
def test_malformed_ledger_fails_closed(tmp_path, content: str) -> None:
    path = tmp_path / "costs.jsonl"
    path.write_text(content)
    ledger = OutcomeBackedBudgetLedger(path)

    with pytest.raises(BudgetLedgerError):
        ledger.snapshot(utc_date=date(2026, 8, 30))


def test_concurrent_reservations_cannot_overcommit_daily_cap(tmp_path) -> None:
    ledger = OutcomeBackedBudgetLedger(tmp_path / "costs.jsonl")

    def reserve(index: int) -> str:
        try:
            _reserve(ledger, f"call-{index}", "15")
        except DailyBudgetExceededError:
            return "blocked"
        return "reserved"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(reserve, (1, 2)))

    assert results == ["blocked", "reserved"]
    snapshot = ledger.snapshot(utc_date=DAY_ONE.date())
    assert snapshot.committed_usd == 15
    assert snapshot.open_reservations == 1


@pytest.mark.parametrize("amount", [-1, float("nan"), float("inf"), True, "not-money"])
def test_invalid_money_is_rejected(tmp_path, amount: object) -> None:
    ledger = OutcomeBackedBudgetLedger(tmp_path / "costs.jsonl")
    with pytest.raises(ValueError, match="finite non-negative"):
        _reserve(ledger, "call-1", amount)
