"""Append-only paid-call budget ledger for the outcome-backed benchmark."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import threading
from types import ModuleType
from typing import Any, TextIO

from aragora.evaluation.outcome_backed_corpus import BENCHMARK_ID

try:
    fcntl: ModuleType | None = importlib.import_module("fcntl")
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None


BUDGET_LEDGER_SCHEMA = "outcome-backed-decision-quality-budget-ledger/1.0"
DAILY_BUDGET_CAP_USD = Decimal("25")
MAX_CALL_ATTEMPTS = 2
SETTLEMENT_OUTCOMES = frozenset(
    {"success", "infrastructure_error", "model_error", "identity_error", "cancelled"}
)
_ZERO_HASH = "0" * 64
_PROCESS_LOCK = threading.RLock()


class BudgetLedgerError(RuntimeError):
    """Raised when the append-only budget ledger is invalid or unusable."""


class DailyBudgetExceededError(BudgetLedgerError):
    """Raised before a paid call would exceed the UTC-day budget."""


@dataclass(frozen=True)
class DailyBudgetSnapshot:
    """One UTC day's settled and outstanding benchmark spend."""

    utc_date: date
    cap_usd: Decimal
    settled_usd: Decimal
    reserved_usd: Decimal
    remaining_usd: Decimal
    open_reservations: int
    event_count: int

    @property
    def committed_usd(self) -> Decimal:
        return self.settled_usd + self.reserved_usd

    @property
    def exceeded(self) -> bool:
        return self.committed_usd > self.cap_usd

    def to_dict(self) -> dict[str, object]:
        return {
            "utc_date": self.utc_date.isoformat(),
            "cap_usd": _money_text(self.cap_usd),
            "settled_usd": _money_text(self.settled_usd),
            "reserved_usd": _money_text(self.reserved_usd),
            "committed_usd": _money_text(self.committed_usd),
            "remaining_usd": _money_text(self.remaining_usd),
            "open_reservations": self.open_reservations,
            "event_count": self.event_count,
            "exceeded": self.exceeded,
        }


def _money(value: object, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite non-negative USD amount")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{field} must be a finite non-negative USD amount")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field} must be a finite non-negative USD amount") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"{field} must be a finite non-negative USD amount")
    return amount


def _money_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _utc_timestamp(value: datetime | None) -> tuple[datetime, str]:
    instant = value or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")
    instant = instant.astimezone(timezone.utc)
    text = instant.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return instant, text


def _canonical_hash(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BudgetLedgerError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


class OutcomeBackedBudgetLedger:
    """Cross-process-safe UTC-day admission and spend ledger.

    Reservations are charged at their conservative estimate until settled,
    then at actual cost. Actual spend is attributed to the reservation's UTC
    day even when settlement arrives after midnight. A second attempt is
    allowed only after the same logical call's first attempt settled as an
    infrastructure error.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        daily_cap_usd: Decimal | int | float | str = DAILY_BUDGET_CAP_USD,
    ) -> None:
        self.path = Path(path)
        self.daily_cap_usd = _money(daily_cap_usd, "daily_cap_usd")
        if self.daily_cap_usd == 0:
            raise ValueError("daily_cap_usd must be greater than zero")

    @contextmanager
    def _locked(self, *, create: bool, exclusive: bool) -> Iterator[TextIO | None]:
        with _PROCESS_LOCK:
            if not create and not self.path.exists():
                yield None
                return
            try:
                if create:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                handle = self.path.open("a+" if create else "r", encoding="utf-8")
            except OSError as exc:
                raise BudgetLedgerError(f"cannot open budget ledger: {exc}") from exc
            try:
                if fcntl is not None:
                    lock = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
                    fcntl.flock(handle.fileno(), lock)
                yield handle
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                handle.close()

    def _read_events(self, handle: TextIO | None) -> list[dict[str, object]]:
        if handle is None:
            return []
        handle.seek(0)
        events: list[dict[str, object]] = []
        previous_hash = _ZERO_HASH
        reservations: dict[str, dict[str, object]] = {}
        settlements: set[str] = set()
        attempts: dict[tuple[str, int], str] = {}
        for line_number, raw in enumerate(handle, start=1):
            if not raw.endswith("\n") or not raw.strip():
                raise BudgetLedgerError(f"invalid ledger record at line {line_number}")
            try:
                event = json.loads(raw, object_pairs_hook=_object_pairs)
            except (json.JSONDecodeError, UnicodeError) as exc:
                raise BudgetLedgerError(
                    f"invalid ledger JSON at line {line_number}: {exc}"
                ) from exc
            if not isinstance(event, dict):
                raise BudgetLedgerError(f"ledger record {line_number} must be an object")
            self._validate_event(
                event,
                line_number=line_number,
                previous_hash=previous_hash,
                events=events,
                reservations=reservations,
                settlements=settlements,
                attempts=attempts,
            )
            previous_hash = str(event["event_sha256"])
            events.append(event)
        return events

    def _validate_event(
        self,
        event: dict[str, object],
        *,
        line_number: int,
        previous_hash: str,
        events: list[dict[str, object]],
        reservations: dict[str, dict[str, object]],
        settlements: set[str],
        attempts: dict[tuple[str, int], str],
    ) -> None:
        common = {
            "schema_version",
            "benchmark_id",
            "sequence",
            "event_type",
            "event_id",
            "reservation_id",
            "logical_call_id",
            "run_id",
            "case_id",
            "condition_id",
            "attempt",
            "recorded_at",
            "utc_date",
            "previous_event_sha256",
            "event_sha256",
        }
        event_type = event.get("event_type")
        if event_type == "reserve":
            expected = common | {"estimated_cost_usd"}
        elif event_type == "settle":
            expected = common | {"actual_cost_usd", "outcome"}
        else:
            raise BudgetLedgerError(f"unknown event type at line {line_number}")
        if set(event) != expected:
            raise BudgetLedgerError(f"unexpected ledger fields at line {line_number}")
        if event.get("schema_version") != BUDGET_LEDGER_SCHEMA:
            raise BudgetLedgerError(f"schema mismatch at line {line_number}")
        if event.get("benchmark_id") != BENCHMARK_ID:
            raise BudgetLedgerError(f"benchmark mismatch at line {line_number}")
        if event.get("sequence") != line_number:
            raise BudgetLedgerError(f"non-contiguous sequence at line {line_number}")
        if event.get("previous_event_sha256") != previous_hash:
            raise BudgetLedgerError(f"hash-chain mismatch at line {line_number}")
        claimed_hash = event.get("event_sha256")
        if not isinstance(claimed_hash, str) or len(claimed_hash) != 64:
            raise BudgetLedgerError(f"invalid event hash at line {line_number}")
        unhashed = dict(event)
        unhashed.pop("event_sha256")
        if _canonical_hash(unhashed) != claimed_hash:
            raise BudgetLedgerError(f"event hash mismatch at line {line_number}")

        for field in (
            "event_id",
            "reservation_id",
            "logical_call_id",
            "run_id",
            "case_id",
            "condition_id",
            "recorded_at",
            "utc_date",
        ):
            try:
                _required_text(event.get(field), field)
            except ValueError as exc:
                raise BudgetLedgerError(f"{exc} at line {line_number}") from exc
        try:
            recorded_at = datetime.fromisoformat(str(event["recorded_at"]).replace("Z", "+00:00"))
            event_date = date.fromisoformat(str(event["utc_date"]))
        except ValueError as exc:
            raise BudgetLedgerError(f"invalid event time at line {line_number}") from exc
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise BudgetLedgerError(f"non-UTC event time at line {line_number}")
        if recorded_at.astimezone(timezone.utc).date() != event_date and event_type == "reserve":
            raise BudgetLedgerError(f"reservation date mismatch at line {line_number}")

        attempt = event.get("attempt")
        if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= 2:
            raise BudgetLedgerError(f"invalid attempt at line {line_number}")
        reservation_id = str(event["reservation_id"])
        logical_call_id = str(event["logical_call_id"])
        if event_type == "reserve":
            if event.get("event_id") != f"reserve:{reservation_id}":
                raise BudgetLedgerError(f"invalid reserve event ID at line {line_number}")
            if reservation_id in reservations:
                raise BudgetLedgerError(f"duplicate reservation at line {line_number}")
            attempt_key = (logical_call_id, attempt)
            if attempt_key in attempts:
                raise BudgetLedgerError(f"duplicate logical call attempt at line {line_number}")
            if attempt == MAX_CALL_ATTEMPTS:
                first_id = attempts.get((logical_call_id, 1))
                first = reservations.get(first_id or "")
                if first is None or first_id not in settlements:
                    raise BudgetLedgerError(
                        f"retry before first attempt settled at line {line_number}"
                    )
                first_settlement = next(
                    (
                        item
                        for item in reversed(events)
                        if item.get("event_type") == "settle"
                        and item.get("reservation_id") == first_id
                    ),
                    None,
                )
                if (
                    first_settlement is None
                    or first_settlement.get("outcome") != "infrastructure_error"
                ):
                    raise BudgetLedgerError(
                        f"retry requires infrastructure failure at line {line_number}"
                    )
            amount = _money(event.get("estimated_cost_usd"), "estimated_cost_usd")
            if event.get("estimated_cost_usd") != _money_text(amount):
                raise BudgetLedgerError(f"non-canonical estimate at line {line_number}")
            reservations[reservation_id] = event
            attempts[attempt_key] = reservation_id
        else:
            if event.get("event_id") != f"settle:{reservation_id}":
                raise BudgetLedgerError(f"invalid settle event ID at line {line_number}")
            reservation = reservations.get(reservation_id)
            if reservation is None:
                raise BudgetLedgerError(f"settlement without reservation at line {line_number}")
            if reservation_id in settlements:
                raise BudgetLedgerError(f"duplicate settlement at line {line_number}")
            for field in (
                "logical_call_id",
                "run_id",
                "case_id",
                "condition_id",
                "attempt",
                "utc_date",
            ):
                if event.get(field) != reservation.get(field):
                    raise BudgetLedgerError(f"settlement identity mismatch at line {line_number}")
            amount = _money(event.get("actual_cost_usd"), "actual_cost_usd")
            if event.get("actual_cost_usd") != _money_text(amount):
                raise BudgetLedgerError(f"non-canonical actual cost at line {line_number}")
            if event.get("outcome") not in SETTLEMENT_OUTCOMES:
                raise BudgetLedgerError(f"invalid settlement outcome at line {line_number}")
            settlements.add(reservation_id)

    def _events(self, handle: TextIO | None) -> list[dict[str, object]]:
        return self._read_events(handle)

    def _check_reservation_admission(
        self,
        events: list[dict[str, object]],
        *,
        reservation_id: str,
        logical_call_id: str,
        attempt: int,
    ) -> None:
        reservations = [event for event in events if event["event_type"] == "reserve"]
        if any(event["reservation_id"] == reservation_id for event in reservations):
            raise BudgetLedgerError("duplicate reservation")
        if any(
            event["logical_call_id"] == logical_call_id and event["attempt"] == attempt
            for event in reservations
        ):
            raise BudgetLedgerError("duplicate logical call attempt")
        if attempt != MAX_CALL_ATTEMPTS:
            return
        first = next(
            (
                event
                for event in reservations
                if event["logical_call_id"] == logical_call_id and event["attempt"] == 1
            ),
            None,
        )
        first_settlement = next(
            (
                event
                for event in events
                if event["event_type"] == "settle"
                and first is not None
                and event["reservation_id"] == first["reservation_id"]
            ),
            None,
        )
        if first is None or first_settlement is None:
            raise BudgetLedgerError("retry before first attempt settled")
        if first_settlement["outcome"] != "infrastructure_error":
            raise BudgetLedgerError("retry requires infrastructure failure")

    def _snapshot(self, events: list[dict[str, object]], utc_date: date) -> DailyBudgetSnapshot:
        reservations = {
            str(event["reservation_id"]): event
            for event in events
            if event["event_type"] == "reserve" and event["utc_date"] == utc_date.isoformat()
        }
        settlements = {
            str(event["reservation_id"]): event
            for event in events
            if event["event_type"] == "settle"
        }
        settled = Decimal("0")
        reserved = Decimal("0")
        open_count = 0
        for reservation_id, reservation in reservations.items():
            settlement = settlements.get(reservation_id)
            if settlement is None:
                reserved += _money(reservation["estimated_cost_usd"], "estimated_cost_usd")
                open_count += 1
            else:
                settled += _money(settlement["actual_cost_usd"], "actual_cost_usd")
        remaining = max(Decimal("0"), self.daily_cap_usd - settled - reserved)
        return DailyBudgetSnapshot(
            utc_date=utc_date,
            cap_usd=self.daily_cap_usd,
            settled_usd=settled,
            reserved_usd=reserved,
            remaining_usd=remaining,
            open_reservations=open_count,
            event_count=len(events),
        )

    def snapshot(self, *, utc_date: date | None = None) -> DailyBudgetSnapshot:
        target_date = utc_date or datetime.now(timezone.utc).date()
        with self._locked(create=False, exclusive=False) as handle:
            return self._snapshot(self._events(handle), target_date)

    def _append(
        self, handle: TextIO, events: list[dict[str, object]], event: dict[str, object]
    ) -> None:
        event["sequence"] = len(events) + 1
        event["previous_event_sha256"] = str(events[-1]["event_sha256"]) if events else _ZERO_HASH
        unhashed = dict(event)
        unhashed.pop("event_sha256")
        event["event_sha256"] = _canonical_hash(unhashed)
        try:
            handle.seek(0, os.SEEK_END)
            handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        except OSError as exc:
            raise BudgetLedgerError(f"cannot append budget ledger: {exc}") from exc

    def reserve(
        self,
        *,
        reservation_id: str,
        logical_call_id: str,
        run_id: str,
        case_id: str,
        condition_id: str,
        attempt: int,
        estimated_cost_usd: Decimal | int | float | str,
        recorded_at: datetime | None = None,
    ) -> dict[str, object]:
        for field, value in (
            ("reservation_id", reservation_id),
            ("logical_call_id", logical_call_id),
            ("run_id", run_id),
            ("case_id", case_id),
            ("condition_id", condition_id),
        ):
            _required_text(value, field)
        if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= 2:
            raise ValueError(f"attempt must be between 1 and {MAX_CALL_ATTEMPTS}")
        estimate = _money(estimated_cost_usd, "estimated_cost_usd")
        instant, timestamp = _utc_timestamp(recorded_at)
        target_date = instant.date()
        with self._locked(create=True, exclusive=True) as handle:
            if handle is None:
                raise BudgetLedgerError("budget ledger handle unavailable")
            events = self._events(handle)
            self._check_reservation_admission(
                events,
                reservation_id=reservation_id,
                logical_call_id=logical_call_id,
                attempt=attempt,
            )
            snapshot = self._snapshot(events, target_date)
            if estimate > 0 and snapshot.committed_usd + estimate > self.daily_cap_usd:
                raise DailyBudgetExceededError(
                    f"UTC-day budget exceeded for {target_date.isoformat()}: "
                    f"committed ${_money_text(snapshot.committed_usd)} + estimated "
                    f"${_money_text(estimate)} > cap ${_money_text(self.daily_cap_usd)}"
                )
            event: dict[str, object] = {
                "schema_version": BUDGET_LEDGER_SCHEMA,
                "benchmark_id": BENCHMARK_ID,
                "sequence": 0,
                "event_type": "reserve",
                "event_id": f"reserve:{reservation_id}",
                "reservation_id": reservation_id,
                "logical_call_id": logical_call_id,
                "run_id": run_id,
                "case_id": case_id,
                "condition_id": condition_id,
                "attempt": attempt,
                "estimated_cost_usd": _money_text(estimate),
                "recorded_at": timestamp,
                "utc_date": target_date.isoformat(),
                "previous_event_sha256": "",
                "event_sha256": "",
            }
            self._append(handle, events, event)
            self._events(handle)
            return event

    def settle(
        self,
        reservation_id: str,
        *,
        actual_cost_usd: Decimal | int | float | str,
        outcome: str,
        recorded_at: datetime | None = None,
    ) -> dict[str, object]:
        _required_text(reservation_id, "reservation_id")
        if outcome not in SETTLEMENT_OUTCOMES:
            raise ValueError("outcome must be one of " + ", ".join(sorted(SETTLEMENT_OUTCOMES)))
        actual = _money(actual_cost_usd, "actual_cost_usd")
        _, timestamp = _utc_timestamp(recorded_at)
        with self._locked(create=True, exclusive=True) as handle:
            if handle is None:
                raise BudgetLedgerError("budget ledger handle unavailable")
            events = self._events(handle)
            reservation = next(
                (
                    event
                    for event in events
                    if event["event_type"] == "reserve"
                    and event["reservation_id"] == reservation_id
                ),
                None,
            )
            if reservation is None:
                raise BudgetLedgerError(f"unknown reservation: {reservation_id}")
            if any(
                event["event_type"] == "settle" and event["reservation_id"] == reservation_id
                for event in events
            ):
                raise BudgetLedgerError(f"reservation already settled: {reservation_id}")
            event = {
                "schema_version": BUDGET_LEDGER_SCHEMA,
                "benchmark_id": BENCHMARK_ID,
                "sequence": 0,
                "event_type": "settle",
                "event_id": f"settle:{reservation_id}",
                "reservation_id": reservation_id,
                "logical_call_id": reservation["logical_call_id"],
                "run_id": reservation["run_id"],
                "case_id": reservation["case_id"],
                "condition_id": reservation["condition_id"],
                "attempt": reservation["attempt"],
                "actual_cost_usd": _money_text(actual),
                "outcome": outcome,
                "recorded_at": timestamp,
                "utc_date": reservation["utc_date"],
                "previous_event_sha256": "",
                "event_sha256": "",
            }
            self._append(handle, events, event)
            self._events(handle)
            return event


__all__ = [
    "BUDGET_LEDGER_SCHEMA",
    "DAILY_BUDGET_CAP_USD",
    "MAX_CALL_ATTEMPTS",
    "SETTLEMENT_OUTCOMES",
    "BudgetLedgerError",
    "DailyBudgetExceededError",
    "DailyBudgetSnapshot",
    "OutcomeBackedBudgetLedger",
]
