"""VIAH — Verifiable Improvements per Agent-Hour.

Productivity metric that the booster-rocket thesis is required to lift
once empty-queue BC-12 idle soaks have proven substrate stability. See
``docs/plans/AGENT_CIVILIZATION_SUBSTRATE.md`` §4 and issue #6067.

The metric:

    VIAH = (
        merged_autonomous_prs * 1.0
        + cruxes_correctly_detected_pre_resolution * 0.5
        + predictions_resolved_above_brier_threshold * 0.5
        - rescues_required * 0.5
        - failed_claims_promoted_without_repair * 1.0
    ) / agent_hours

Inputs are read from any ledger satisfying the structural
:class:`ViahLedger` protocol, such as :class:`aragora.swarm.shift_ledger.
ShiftLedger`. Signals that depend on AGT-05 wiring (crux correctness,
prediction resolutions, failed claims) are accepted as optional sidecar
counts so this module can land before AGT-05 settlement is live; counts
default to zero when not supplied.

The metric is **diagnostic, not gating**. It supplements (not replaces)
the TW-02 no-rescue success rate. The substrate is paying for itself
when VIAH trends up week-over-week without operator babysitting.
"""

from __future__ import annotations

import logging
import math
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, TypeVar, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class ViahLedgerEntry(Protocol):
    """One ledger row as VIAH reads it."""

    @property
    def entry_type(self) -> str: ...

    @property
    def timestamp(self) -> str: ...

    @property
    def payload(self) -> dict[str, Any]: ...


_EntryT = TypeVar("_EntryT", bound=ViahLedgerEntry)
_EntryT_co = TypeVar("_EntryT_co", bound=ViahLedgerEntry, covariant=True)


@runtime_checkable
class ViahLedger(Protocol[_EntryT_co]):
    """Ledger surface VIAH reads from and appends snapshots to.

    :class:`aragora.swarm.shift_ledger.ShiftLedger` satisfies this protocol
    structurally; evaluation code must not import it (layer contract).
    """

    @property
    def path(self) -> Path: ...

    def read_all(self) -> Sequence[_EntryT_co]: ...

    def read_by_type(self, entry_type: str) -> Sequence[_EntryT_co]: ...

    def append(self, entry_type: str, **payload: Any) -> _EntryT_co: ...


# Default coefficients matching the AGT-06 plan
DEFAULT_PR_WEIGHT = 1.0
DEFAULT_CRUX_WEIGHT = 0.5
DEFAULT_PREDICTION_WEIGHT = 0.5
DEFAULT_RESCUE_WEIGHT = 0.5
DEFAULT_FAILED_CLAIM_WEIGHT = 1.0
DEFAULT_BRIER_THRESHOLD = 0.20


@dataclass(frozen=True)
class ViahCoefficients:
    """Per-signal weights for the VIAH score."""

    merged_pr_weight: float = DEFAULT_PR_WEIGHT
    crux_weight: float = DEFAULT_CRUX_WEIGHT
    prediction_weight: float = DEFAULT_PREDICTION_WEIGHT
    rescue_weight: float = DEFAULT_RESCUE_WEIGHT
    failed_claim_weight: float = DEFAULT_FAILED_CLAIM_WEIGHT


@dataclass(frozen=True)
class ViahReport:
    """One VIAH measurement over a time window."""

    window_start: str
    window_end: str
    window_hours: float
    agent_hours: float

    # Positive signals
    merged_autonomous_prs: int
    cruxes_correctly_detected: int
    predictions_above_brier_threshold: int

    # Negative signals
    rescues_required: int
    failed_claims_promoted_without_repair: int

    # Derived
    viah: float | None
    coefficients: ViahCoefficients

    # Inputs detail (for audit/debug)
    inputs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "window_hours": self.window_hours,
            "agent_hours": self.agent_hours,
            "merged_autonomous_prs": self.merged_autonomous_prs,
            "cruxes_correctly_detected": self.cruxes_correctly_detected,
            "predictions_above_brier_threshold": self.predictions_above_brier_threshold,
            "rescues_required": self.rescues_required,
            "failed_claims_promoted_without_repair": (self.failed_claims_promoted_without_repair),
            "viah": self.viah,
            "coefficients": {
                "merged_pr_weight": self.coefficients.merged_pr_weight,
                "crux_weight": self.coefficients.crux_weight,
                "prediction_weight": self.coefficients.prediction_weight,
                "rescue_weight": self.coefficients.rescue_weight,
                "failed_claim_weight": self.coefficients.failed_claim_weight,
            },
            "inputs": dict(self.inputs),
        }


def viah_score(
    *,
    merged_autonomous_prs: int,
    cruxes_correctly_detected: int,
    predictions_above_brier_threshold: int,
    rescues_required: int,
    failed_claims_promoted_without_repair: int,
    agent_hours: float,
    coefficients: ViahCoefficients | None = None,
) -> float | None:
    """Compute the raw VIAH score from the signal counts.

    Returns ``None`` when ``agent_hours`` is non-positive — VIAH is
    undefined for an empty observation window.
    """
    if agent_hours <= 0 or not math.isfinite(agent_hours):
        return None
    coef = coefficients or ViahCoefficients()
    numerator = (
        merged_autonomous_prs * coef.merged_pr_weight
        + cruxes_correctly_detected * coef.crux_weight
        + predictions_above_brier_threshold * coef.prediction_weight
        - rescues_required * coef.rescue_weight
        - failed_claims_promoted_without_repair * coef.failed_claim_weight
    )
    return numerator / agent_hours


def compute_viah(
    *,
    ledger: ViahLedger[ViahLedgerEntry],
    window_hours: float = 168.0,
    now: datetime | None = None,
    cruxes_correctly_detected: int = 0,
    predictions_above_brier_threshold: int = 0,
    failed_claims_promoted_without_repair: int = 0,
    coefficients: ViahCoefficients | None = None,
) -> ViahReport:
    """Compute a VIAH report from a :class:`ViahLedger` over ``window_hours``.

    Signals derived from the ledger:

    - ``merged_autonomous_prs``: count of ``pr_merged`` entries in the window
    - ``rescues_required``: cumulative ``rescue_count`` payload from
      ``cycle_tick`` entries (older shift code may set the field to 0)
    - ``agent_hours``: sum of completed ``shift_start`` → ``shift_stop``
      durations falling within the window, plus any in-progress shift's
      partial duration up to ``now``

    Sidecar signals (``cruxes_correctly_detected``,
    ``predictions_above_brier_threshold``, ``failed_claims_promoted_without_repair``)
    default to zero so this module can land before AGT-05 settlement
    wires them; once AGT-05 is live, the AGT-05 settlement path will
    supply these counts from resolved CruxSets and prediction-market
    resolutions.

    Returns a :class:`ViahReport`. ``ViahReport.viah`` is ``None`` when
    the window contains no agent-hours.
    """
    coef = coefficients or ViahCoefficients()
    reference = (now or datetime.now(tz=UTC)).astimezone(UTC)
    window_start = reference - timedelta(hours=window_hours)

    entries_in_window = _entries_within(
        ledger.read_all(),
        start=window_start,
        end=reference,
    )

    merged = sum(1 for e in entries_in_window if e.entry_type == "pr_merged")
    rescues = _sum_rescue_counts(entries_in_window)
    agent_hours = _agent_hours_from_shifts(
        ledger.read_all(),
        start=window_start,
        end=reference,
    )

    score = viah_score(
        merged_autonomous_prs=merged,
        cruxes_correctly_detected=cruxes_correctly_detected,
        predictions_above_brier_threshold=predictions_above_brier_threshold,
        rescues_required=rescues,
        failed_claims_promoted_without_repair=failed_claims_promoted_without_repair,
        agent_hours=agent_hours,
        coefficients=coef,
    )

    return ViahReport(
        window_start=_iso(window_start),
        window_end=_iso(reference),
        window_hours=window_hours,
        agent_hours=agent_hours,
        merged_autonomous_prs=merged,
        cruxes_correctly_detected=cruxes_correctly_detected,
        predictions_above_brier_threshold=predictions_above_brier_threshold,
        rescues_required=rescues,
        failed_claims_promoted_without_repair=failed_claims_promoted_without_repair,
        viah=score,
        coefficients=coef,
        inputs={
            "ledger_path": str(ledger.path),
            "entries_in_window": len(entries_in_window),
        },
    )


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except (ValueError, AttributeError):
        return None


def _entries_within(
    entries: Sequence[ViahLedgerEntry],
    *,
    start: datetime,
    end: datetime,
) -> list[ViahLedgerEntry]:
    out: list[ViahLedgerEntry] = []
    for entry in entries:
        ts = _parse_iso(entry.timestamp)
        if ts is None:
            continue
        if start <= ts <= end:
            out.append(entry)
    return out


def _sum_rescue_counts(entries: Sequence[ViahLedgerEntry]) -> int:
    """Sum rescue_count payloads from cycle_tick entries.

    Older shifts may not have written rescue_count; missing values
    are treated as zero rather than discarded. This keeps the metric
    defined across mixed-version ledgers.
    """
    total = 0
    for entry in entries:
        if entry.entry_type != "cycle_tick":
            continue
        raw = entry.payload.get("rescue_count")
        try:
            total += int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    return total


def _agent_hours_from_shifts(
    entries: Sequence[ViahLedgerEntry],
    *,
    start: datetime,
    end: datetime,
) -> float:
    """Sum durations of shifts that fall (even partially) inside the window.

    A shift's contribution is the intersection of its [start, stop]
    interval with the [window_start, window_end] interval. Shifts that
    are still in-progress (no shift_stop after their shift_start) are
    treated as ending at ``end``.
    """
    starts: dict[str, datetime] = {}
    pairs: list[tuple[datetime, datetime]] = []

    for entry in entries:
        ts = _parse_iso(entry.timestamp)
        if ts is None:
            continue
        shift_id = str(entry.payload.get("shift_id") or "")
        if entry.entry_type == "shift_start":
            if shift_id:
                starts[shift_id] = ts
            else:
                # Anonymous shifts: we still need to pair them; use a
                # fallback identifier per timestamp
                starts[f"_anon_{ts.isoformat()}"] = ts
        elif entry.entry_type == "shift_stop":
            key = shift_id if shift_id and shift_id in starts else None
            if key is None:
                # Pair with the earliest open shift if no id matches
                if not starts:
                    continue
                key = next(iter(starts))
            shift_start = starts.pop(key)
            pairs.append((shift_start, ts))

    # Treat any unmatched shift_start as still-running
    for shift_start in starts.values():
        pairs.append((shift_start, end))

    total_hours = 0.0
    for shift_start, shift_end in pairs:
        if shift_end < shift_start:
            continue
        intersect_start = max(shift_start, start)
        intersect_end = min(shift_end, end)
        if intersect_end <= intersect_start:
            continue
        total_hours += (intersect_end - intersect_start).total_seconds() / 3600.0
    return total_hours


VIAH_TREND_FLAG = "ARAGORA_VIAH_TREND_ENABLED"


def viah_trend_enabled() -> bool:
    """Return True when the rolling VIAH trend surface is explicitly enabled.

    Reads ``ARAGORA_VIAH_TREND_ENABLED`` from the environment.  Defaults to
    False so the surface is dormant until the AGT-06 activation gate opens.
    """
    return str(os.environ.get(VIAH_TREND_FLAG) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass(frozen=True)
class ViahTrendPoint:
    """Single-week VIAH measurement within a rolling trend."""

    week_index: int
    window_start: str
    window_end: str
    viah: float | None
    merged_autonomous_prs: int
    agent_hours: float


@dataclass(frozen=True)
class ViahTrend:
    """Rolling VIAH trend over N consecutive weeks.

    ``trend_direction`` is derived from the slope of scored (non-None)
    week VIAHs.  Values: ``"positive"``, ``"flat"``, ``"negative"``,
    ``"insufficient_data"`` (< 2 scored weeks).
    """

    weeks_requested: int
    points: list[ViahTrendPoint]
    trend_direction: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "weeks_requested": self.weeks_requested,
            "trend_direction": self.trend_direction,
            "points": [
                {
                    "week_index": p.week_index,
                    "window_start": p.window_start,
                    "window_end": p.window_end,
                    "viah": p.viah,
                    "merged_autonomous_prs": p.merged_autonomous_prs,
                    "agent_hours": p.agent_hours,
                }
                for p in self.points
            ],
        }


def _trend_direction(points: list[ViahTrendPoint]) -> str:
    """Classify trend direction from a list of weekly VIAH points.

    Uses ordinary-least-squares slope over the scored (non-None) points.
    Returns ``"insufficient_data"`` when fewer than 2 points have a score.
    A slope within ±0.02 VIAH/week is considered flat.
    """
    scored = [(p.week_index, p.viah) for p in points if p.viah is not None]
    if len(scored) < 2:
        return "insufficient_data"
    n = len(scored)
    xs = [float(i) for i, _ in scored]
    ys = [v for _, v in scored]  # type: ignore[misc]
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    num = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(xs, ys))
    den = sum((xi - x_mean) ** 2 for xi in xs)
    slope = (num / den) if den != 0.0 else 0.0
    if slope > 0.02:
        return "positive"
    if slope < -0.02:
        return "negative"
    return "flat"


def rolling_viah_trend(
    *,
    ledger: ViahLedger[ViahLedgerEntry],
    weeks: int = 4,
    week_hours: float = 168.0,
    now: datetime | None = None,
    coefficients: ViahCoefficients | None = None,
) -> ViahTrend:
    """Compute rolling VIAH trend over ``weeks`` consecutive one-week windows.

    Windows are numbered 0 (oldest) … ``weeks-1`` (most recent), where
    week 0 ends at ``now - (weeks-1) * week_hours`` and week ``weeks-1``
    ends at ``now``.

    Gated behind ``ARAGORA_VIAH_TREND_ENABLED``.  Raises ``RuntimeError``
    when the flag is not set so callers fail loudly instead of silently
    returning empty data.

    Sidecar signals (crux-correctness, prediction resolutions, failed
    claims) default to zero — they are wired by AGT-05 once live.
    """
    if not viah_trend_enabled():
        raise RuntimeError(
            f"rolling VIAH trend surface is disabled; set {VIAH_TREND_FLAG}=1 to enable"
        )
    if weeks < 1:
        raise ValueError("weeks must be >= 1")

    reference = (now or datetime.now(tz=UTC)).astimezone(UTC)
    points: list[ViahTrendPoint] = []

    for idx in range(weeks):
        # week 0 is the oldest; week weeks-1 is the most recent
        offset_from_now = (weeks - 1 - idx) * week_hours
        week_end = reference - timedelta(hours=offset_from_now)
        report = compute_viah(
            ledger=ledger,
            window_hours=week_hours,
            now=week_end,
            coefficients=coefficients,
        )
        points.append(
            ViahTrendPoint(
                week_index=idx,
                window_start=report.window_start,
                window_end=report.window_end,
                viah=report.viah,
                merged_autonomous_prs=report.merged_autonomous_prs,
                agent_hours=report.agent_hours,
            )
        )

    return ViahTrend(
        weeks_requested=weeks,
        points=points,
        trend_direction=_trend_direction(points),
    )


VIAH_SNAPSHOT_ENTRY_TYPE = "viah_snapshot"


def persist_viah_snapshot(
    *,
    ledger: ViahLedger[_EntryT],
    report: ViahReport,
) -> _EntryT:
    """Persist a ViahReport to the ledger as a ``viah_snapshot`` entry.

    Returns whatever ``ledger.append`` returns (a ``LedgerEntry`` for a
    :class:`aragora.swarm.shift_ledger.ShiftLedger`).

    Gated behind ``ARAGORA_VIAH_TREND_ENABLED`` — the same flag that guards
    :func:`rolling_viah_trend`.  Raises ``RuntimeError`` when the flag is
    off so callers fail loudly rather than silently dropping snapshots.

    The entry payload mirrors :meth:`ViahReport.to_dict` (minus the nested
    ``coefficients`` and ``inputs`` sub-dicts) so ledger consumers can
    reconstruct the key signals without deserializing nested objects.
    """
    if not viah_trend_enabled():
        raise RuntimeError(
            f"VIAH snapshot persistence is disabled; set {VIAH_TREND_FLAG}=1 to enable"
        )
    return ledger.append(
        VIAH_SNAPSHOT_ENTRY_TYPE,
        window_start=report.window_start,
        window_end=report.window_end,
        window_hours=report.window_hours,
        agent_hours=report.agent_hours,
        viah=report.viah,
        merged_autonomous_prs=report.merged_autonomous_prs,
        cruxes_correctly_detected=report.cruxes_correctly_detected,
        predictions_above_brier_threshold=report.predictions_above_brier_threshold,
        rescues_required=report.rescues_required,
        failed_claims_promoted_without_repair=report.failed_claims_promoted_without_repair,
    )


def read_viah_snapshots(
    *,
    ledger: ViahLedger[ViahLedgerEntry],
    max_count: int | None = None,
) -> list[dict[str, Any]]:
    """Return persisted VIAH snapshot payloads from the ledger, newest-last.

    Read-only and always safe to call regardless of the flag state —
    an empty ledger simply returns an empty list.

    Args:
        ledger: The :class:`ViahLedger` to read (for example a
            :class:`~aragora.swarm.shift_ledger.ShiftLedger`).
        max_count: If given, return at most this many most-recent snapshots.
    """
    entries = ledger.read_by_type(VIAH_SNAPSHOT_ENTRY_TYPE)
    payloads = [e.payload for e in entries]
    if max_count is not None and max_count > 0:
        payloads = payloads[-max_count:]
    return payloads


__all__ = [
    "DEFAULT_BRIER_THRESHOLD",
    "DEFAULT_CRUX_WEIGHT",
    "DEFAULT_FAILED_CLAIM_WEIGHT",
    "DEFAULT_PREDICTION_WEIGHT",
    "DEFAULT_PR_WEIGHT",
    "DEFAULT_RESCUE_WEIGHT",
    "VIAH_SNAPSHOT_ENTRY_TYPE",
    "VIAH_TREND_FLAG",
    "ViahCoefficients",
    "ViahLedger",
    "ViahLedgerEntry",
    "ViahReport",
    "ViahTrend",
    "ViahTrendPoint",
    "compute_viah",
    "persist_viah_snapshot",
    "read_viah_snapshots",
    "rolling_viah_trend",
    "viah_score",
    "viah_trend_enabled",
]
