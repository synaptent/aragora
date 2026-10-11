"""Adapter from on-disk auto-handle calibration + settlement receipts to
:class:`aragora.review.invalidation.InvalidatedDecision` (gap #6375 phase 2).

This module wires the empirical-threshold framework that landed in
phase 1 (#6602) to the data already on disk:

  - :class:`aragora.triage.auto_handle_calibration.AutoHandleCalibrationStore`
    rows whose ``outcome`` is one of the failure constants
    (:data:`OUTCOME_REVERT`, :data:`OUTCOME_INCIDENT`,
    :data:`OUTCOME_HUMAN_OVERRIDE`) — these are *auto-handled*
    invalidations.
  - settlement-receipt JSON files under
    ``<store_root>/receipts/`` — used as the *denominator* for
    human-settled decisions (the per-window total against which the
    baseline rate is computed).

Both surfaces are read-only here; the adapter does not mutate either
store. Connection lifecycle on the calibration store mirrors that
module's contract (file-backed stores open/close per call;
``:memory:`` stores reuse the persistent connection).

Honest caveats
--------------

The settlement-receipt schema does not yet record *post-settlement*
invalidation signals (revert, incident, follow-up redo). That means:

- Human-settled decisions can be *counted* (denominator) but not yet
  *classified* as invalidated from receipts alone. Until receipts grow
  outcome fields, the human-side numerator is 0; the corresponding
  note is added to the :class:`BaselineMeasurement` so consumers can
  tell "no invalidations" apart from "no signal source".
- Auto-handled decisions DO carry outcomes (the calibration store's
  whole purpose) so they classify cleanly.

This is the same shape #6373 / #6440 chose for the rolling-window
metrics: emit ``None`` honestly when an upstream signal is missing,
and surface the gap in ``notes`` so callers cannot silently
mistake suppressed metrics for measured zero rates.

Phase boundaries
----------------

Phase 1 (#6602): pure-function classification + baseline + threshold.
Phase 2 (this PR): on-disk adapters reading existing stores.
Phase 3 (codex, #6375 step B): recalibration scheduler + ``ThresholdUpdateReceipt``.
Phase 4 (separate PR): CLI surfacing — ``aragora review-queue baseline``.
Phase 5 (separate PR, requires real data): replace the literal ``5%``
in ``docs/THESIS.md`` Commitment 3.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from aragora.review.invalidation import (
    BaselineMeasurement,
    DEFAULT_BASELINE_WINDOW_DAYS,
    DEFAULT_MIN_BASELINE_SAMPLES,
    DEFAULT_REVERT_WINDOW_DAYS,
    INVALIDATION_HUMAN_OVERRIDE_REDO,
    INVALIDATION_POST_MERGE_INCIDENT,
    INVALIDATION_REOPENED_PR,
    INVALIDATION_REVERT_WITHIN_WINDOW,
    INVALIDATION_ROLLBACK,
    InvalidatedDecision,
    compute_baseline,
)
from aragora.review.threshold_recalibration import InvalidationRecalibrationSample
from aragora.triage.auto_handle_calibration import (
    AutoHandleCalibrationStore,
    OUTCOME_HUMAN_OVERRIDE,
    OUTCOME_INCIDENT,
    OUTCOME_REVERT,
    OUTCOME_SUCCESS,
)

__all__ = [
    "DEFAULT_REVIEW_QUEUE_SUBDIR",
    "RECEIPTS_SUBDIR",
    "ReviewQueueInvalidationEventSource",
    "iter_invalidations_from_calibration_store",
    "iter_invalidations_from_settlement_receipts",
    "count_decisions_from_settlement_receipts",
    "measure_baseline_from_stores",
    "resolve_review_queue_root",
]

UTC = timezone.utc
logger = logging.getLogger(__name__)

DEFAULT_REVIEW_QUEUE_SUBDIR = ".aragora/review-queue"
RECEIPTS_SUBDIR = "receipts"

# Map calibration-store outcomes to invalidation signals.
# OUTCOME_SUCCESS does not produce an invalidation signal; the other
# three failure outcomes each map to one canonical signal.
_OUTCOME_TO_SIGNAL: dict[str, str] = {
    OUTCOME_REVERT: INVALIDATION_REVERT_WITHIN_WINDOW,
    OUTCOME_INCIDENT: INVALIDATION_POST_MERGE_INCIDENT,
    OUTCOME_HUMAN_OVERRIDE: INVALIDATION_HUMAN_OVERRIDE_REDO,
}

_FAILURE_OUTCOMES = frozenset(_OUTCOME_TO_SIGNAL.keys())


class ReviewQueueInvalidationEventSource:
    """Protocol adapter for the threshold recalibration scheduler.

    This class keeps the event-source policy in one place: auto-handle
    calibration rows provide auto-handled numerator + denominator data, while
    settlement receipts provide the human-settled denominator and only provide
    human numerator events when explicit future-schema invalidation fields are
    present.
    """

    source_name = "aragora.review.invalidation_event_source"
    source_version = "round30f.v1"

    def __init__(
        self,
        *,
        calibration_store: AutoHandleCalibrationStore,
        review_queue_root: str | Path | None = None,
        revert_window_days: int = DEFAULT_REVERT_WINDOW_DAYS,
    ) -> None:
        self.calibration_store = calibration_store
        self.review_queue_root = review_queue_root
        self.revert_window_days = int(revert_window_days)

    def collect_recalibration_sample(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
    ) -> InvalidationRecalibrationSample:
        """Return denominator + invalidation data for one measurement window."""
        window_start = _ensure_utc(window_start)
        window_end = _ensure_utc(window_end)
        if window_end <= window_start:
            raise ValueError("window_end must be after window_start")
        window_days = max(1, int((window_end - window_start).total_seconds() // 86400))

        auto_invalidations = list(
            iter_invalidations_from_calibration_store(
                self.calibration_store,
                window_end=window_end,
                window_days=window_days,
            )
        )
        auto_total = _count_calibration_decisions_in_window(
            self.calibration_store,
            window_end=window_end,
            window_days=window_days,
        )
        human_invalidations = [
            d
            for d in iter_invalidations_from_settlement_receipts(
                store_root=self.review_queue_root,
                revert_window_days=self.revert_window_days,
            )
            if window_start <= d.settled_at <= window_end
        ]
        human_total = count_decisions_from_settlement_receipts(
            store_root=self.review_queue_root,
            window_end=window_end,
            window_days=window_days,
        )

        notes: dict[str, str] = {
            "human_denominator_source": "review-queue settlement receipts",
            "auto_handle_source": "auto-handle calibration store",
        }
        if human_total:
            v2_observed_count = _count_receipts_with_v2_outcome_fields(
                store_root=self.review_queue_root,
                window_end=window_end,
                window_days=window_days,
            )
            coverage = (
                "complete"
                if v2_observed_count == human_total
                else "partial"
                if v2_observed_count
                else "absent"
            )
            notes["human_invalidations_coverage"] = coverage
            notes["human_invalidations_observed_count"] = str(v2_observed_count)
            notes["human_settlement_receipt_count"] = str(human_total)
            if coverage == "complete" and not human_invalidations:
                notes["human_invalidations_source"] = (
                    "settlement-receipt schema-v2 outcome fields are present on all "
                    "receipts in the window, but no receipt in the window "
                    "fired any of the five canonical signals. Treat as measured "
                    "zero because the human invalidation observation coverage is complete."
                )
            elif coverage != "complete" and not human_invalidations:
                notes["human_invalidations_source"] = (
                    f"schema_gap_human_numerator: settlement-receipt v2 outcome "
                    f"fields are populated on {v2_observed_count}/{human_total} "
                    "receipts in the window. Run "
                    "aragora.review.settlement_outcome.observe_outcome over the "
                    "window to close this gap. Until then, human-side numerator "
                    "is partial data availability, not a full-window measurement."
                )

        return InvalidationRecalibrationSample(
            invalidations=tuple(auto_invalidations + human_invalidations),
            total_human_settled=human_total,
            total_auto_handled=auto_total,
            source_name=self.source_name,
            source_version=self.source_version,
            collected_at=window_end,
            notes=notes,
        )


# ---------------------------------------------------------------------------
# Public API — settlement-receipt side (human-settled denominators)
# ---------------------------------------------------------------------------


def resolve_review_queue_root(override: str | Path | None = None) -> Path:
    """Resolve the canonical review-queue store root.

    Mirrors the resolution order used by
    :func:`aragora.triage.event_source.resolve_store_root` so this
    adapter and the metrics adapter read from the same tree:

    1. Explicit ``override`` argument.
    2. ``ARAGORA_REVIEW_QUEUE_ROOT`` environment variable.
    3. Walk up from cwd looking for ``.aragora/`` or ``.git/``; return
       ``<found>/.aragora/review-queue``.
    4. Fallback: ``cwd/.aragora/review-queue``.
    """
    if override is not None:
        return Path(override)
    env = os.environ.get("ARAGORA_REVIEW_QUEUE_ROOT")
    if env:
        return Path(env)
    cwd = Path.cwd()
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".aragora").exists() or (candidate / ".git").exists():
            return candidate / ".aragora" / "review-queue"
    return cwd / ".aragora" / "review-queue"


def count_decisions_from_settlement_receipts(
    *,
    store_root: str | Path | None = None,
    window_end: datetime,
    window_days: int = DEFAULT_BASELINE_WINDOW_DAYS,
) -> int:
    """Return the count of human-settled decisions in the window.

    Each settlement receipt corresponds to exactly one human-settled
    decision (the writer in
    :mod:`aragora.cli.commands.review_queue` emits one per
    ``review-queue act``). Receipts whose ``reviewed_at`` cannot be
    parsed are skipped with a WARNING log; this matches the resilience
    posture of :mod:`aragora.triage.event_source`.

    Args:
        store_root: Path to the review-queue store; resolved via
            :func:`resolve_review_queue_root` when ``None``.
        window_end: Right edge of the measurement window (inclusive).
        window_days: Width of the window in days. Defaults to
            :data:`DEFAULT_BASELINE_WINDOW_DAYS`.
    """
    return sum(
        1
        for _ in _iter_in_window_settlement_receipt_payloads(
            store_root=store_root,
            window_end=window_end,
            window_days=window_days,
            warn_invalid_reviewed_at=True,
        )
    )


_V2_OUTCOME_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "outcome_revert_within_window",
        "outcome_post_merge_incident",
        "outcome_human_override_redo",
        "outcome_rollback",
        "outcome_reopened_pr",
        "outcome_observed_at",
    }
)

_V2_OUTCOME_SIGNAL_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "outcome_revert_within_window",
        "outcome_post_merge_incident",
        "outcome_human_override_redo",
        "outcome_rollback",
        "outcome_reopened_pr",
    }
)


def _iter_in_window_settlement_receipt_payloads(
    *,
    store_root: str | Path | None = None,
    window_end: datetime,
    window_days: int = DEFAULT_BASELINE_WINDOW_DAYS,
    warn_invalid_reviewed_at: bool = False,
) -> Iterator[dict[str, Any]]:
    """Yield parseable in-window settlement receipt payloads.

    Denominator counts and v2-observation coverage must use this same receipt
    set so "complete" coverage cannot be inferred from a broader scan than the
    human-settlement denominator.
    """
    if window_days <= 0:
        raise ValueError("window_days must be positive")
    window_end = _ensure_utc(window_end)
    window_start = window_end - timedelta(days=window_days)

    receipts_dir = resolve_review_queue_root(store_root) / RECEIPTS_SUBDIR
    if not receipts_dir.exists():
        return

    try:
        candidates = sorted(
            (p for p in receipts_dir.iterdir() if p.is_file() and p.suffix == ".json"),
            key=lambda p: p.name,
        )
    except OSError as exc:
        logger.warning("review.invalidation_event_source: cannot list %s: %s", receipts_dir, exc)
        return

    for path in candidates:
        payload = _safe_read_json(path)
        if payload is None:
            continue
        reviewed_raw = payload.get("reviewed_at")
        if not reviewed_raw:
            continue
        try:
            reviewed_at = _parse_iso(str(reviewed_raw))
        except ValueError:
            if warn_invalid_reviewed_at:
                logger.warning(
                    "review.invalidation_event_source: receipt %s has invalid reviewed_at=%r",
                    path,
                    reviewed_raw,
                )
            continue
        if window_start <= reviewed_at <= window_end:
            yield payload


def _receipt_has_any_v2_outcome_field(payload: dict[str, Any]) -> bool:
    return any(
        field_name in payload and payload[field_name] is not None
        for field_name in _V2_OUTCOME_FIELD_NAMES
    )


def _receipt_has_complete_v2_outcome_fields(payload: dict[str, Any]) -> bool:
    return all(
        field_name in payload and payload[field_name] is not None
        for field_name in _V2_OUTCOME_SIGNAL_FIELD_NAMES
    )


def _any_receipt_has_v2_outcome_fields(
    *,
    store_root: str | Path | None = None,
    window_end: datetime,
    window_days: int = DEFAULT_BASELINE_WINDOW_DAYS,
    probe_cap: int = 50,
) -> bool:
    """Return True iff any receipt in the window carries a v2 outcome field
    that is not ``None``.

    A receipt is considered to "have v2 outcome fields" iff at least one of
    the six v2 field names is present in the JSON payload AND its value is
    not ``None``. Reading-only; bounded to ``probe_cap`` receipts to avoid
    scanning very large stores.

    This is the discriminator behind the two ``human_invalidations_source``
    notes in :func:`measure_baseline_from_disk`.
    """
    probed = 0
    for payload in _iter_in_window_settlement_receipt_payloads(
        store_root=store_root,
        window_end=window_end,
        window_days=window_days,
    ):
        if probed >= probe_cap:
            break
        probed += 1
        if _receipt_has_any_v2_outcome_field(payload):
            return True
    return False


def _count_receipts_with_v2_outcome_fields(
    *,
    store_root: str | Path | None = None,
    window_end: datetime,
    window_days: int = DEFAULT_BASELINE_WINDOW_DAYS,
) -> int:
    """Return in-window receipts whose five v2 outcome signals are complete."""
    return sum(
        1
        for payload in _iter_in_window_settlement_receipt_payloads(
            store_root=store_root,
            window_end=window_end,
            window_days=window_days,
        )
        if _receipt_has_complete_v2_outcome_fields(payload)
    )


def iter_invalidations_from_settlement_receipts(
    *,
    store_root: str | Path | None = None,
    revert_window_days: int = DEFAULT_REVERT_WINDOW_DAYS,
) -> Iterator[InvalidatedDecision]:
    """Yield :class:`InvalidatedDecision` for receipts that already
    record invalidation signals.

    Today's settlement-receipt schema does not carry post-settlement
    invalidation fields (revert/incident/redo). When future schema
    extensions add them, this iterator will start yielding events
    without consumer changes — the dispatch table here is the only
    place that needs to grow.

    Until then this iterator yields nothing for almost every receipt,
    by design. Callers should treat the human-settled invalidation
    *numerator* as ``0`` and rely on the per-field ``notes`` map on
    :class:`BaselineMeasurement` to surface the gap.

    The ``revert_window_days`` argument is reserved for the future
    schema; current code does not consult it.
    """
    receipts_dir = resolve_review_queue_root(store_root) / RECEIPTS_SUBDIR
    if not receipts_dir.exists():
        return
    try:
        candidates = sorted(
            (p for p in receipts_dir.iterdir() if p.is_file() and p.suffix == ".json"),
            key=lambda p: p.name,
        )
    except OSError as exc:
        logger.warning("review.invalidation_event_source: cannot list %s: %s", receipts_dir, exc)
        return
    for path in candidates:
        payload = _safe_read_json(path)
        if payload is None:
            continue
        decision = _invalidation_from_settlement_receipt(
            payload,
            source_path=path,
            revert_window_days=revert_window_days,
        )
        if decision is not None:
            yield decision


# ---------------------------------------------------------------------------
# Public API — calibration-store side (auto-handled invalidations)
# ---------------------------------------------------------------------------


def iter_invalidations_from_calibration_store(
    store: AutoHandleCalibrationStore,
    *,
    window_end: datetime | None = None,
    window_days: int = DEFAULT_BASELINE_WINDOW_DAYS,
) -> Iterator[InvalidatedDecision]:
    """Yield one :class:`InvalidatedDecision` per failure-outcome row
    in the auto-handle calibration store.

    Pulls directly from the store's underlying SQLite. Read-only —
    does not open a write transaction.

    Args:
        store: An :class:`AutoHandleCalibrationStore` instance.
        window_end: Optional right edge for filtering rows. ``None``
            yields every failure-outcome row regardless of date.
        window_days: When ``window_end`` is provided, restricts to
            rows whose ``decided_at`` is within
            ``[window_end - window_days, window_end]``.
    """
    if window_days <= 0:
        raise ValueError("window_days must be positive")

    end_ts: float | None = None
    start_ts: float | None = None
    if window_end is not None:
        window_end = _ensure_utc(window_end)
        end_ts = window_end.timestamp()
        start_ts = end_ts - (window_days * 86400)

    query = (
        "SELECT decision_id, auto_handle_path, decision_class, pr_url, pr_number, "
        "outcome, decided_at, metadata_json "
        "FROM auto_handle_decisions "
        "WHERE outcome IN (?, ?, ?) "
        + ("AND decided_at >= ? AND decided_at <= ? " if end_ts is not None else "")
        + "ORDER BY decided_at ASC"
    )
    params: list[Any] = [OUTCOME_REVERT, OUTCOME_INCIDENT, OUTCOME_HUMAN_OVERRIDE]
    if end_ts is not None and start_ts is not None:
        params.extend([float(start_ts), float(end_ts)])

    rows = _read_rows(store, query, params)
    for row in rows:
        decision = _invalidation_from_calibration_row(row)
        if decision is not None:
            yield decision


# ---------------------------------------------------------------------------
# Public API — top-level: full baseline measurement from the live stores
# ---------------------------------------------------------------------------


def measure_baseline_from_stores(
    *,
    calibration_store: AutoHandleCalibrationStore,
    review_queue_root: str | Path | None = None,
    window_end: datetime,
    window_days: int = DEFAULT_BASELINE_WINDOW_DAYS,
    min_samples: int = DEFAULT_MIN_BASELINE_SAMPLES,
    revert_window_days: int = DEFAULT_REVERT_WINDOW_DAYS,
) -> BaselineMeasurement:
    """Measure the empirical invalidation baseline from on-disk stores.

    Combines:

      - Auto-handled invalidations from the calibration store
        (numerator + denominator both queryable from there).
      - Human-settled invalidations from settlement receipts
        (numerator typically 0 today; denominator from receipt count).

    Returns a :class:`BaselineMeasurement` whose ``notes`` map names
    the fields that are unmeasurable from current schemas. The
    ``BaselineMeasurement`` is *not* persisted here — callers that
    want a signed receipt should pass it to the recalibration
    scheduler (#6375 step B, codex).

    Args:
        calibration_store: An :class:`AutoHandleCalibrationStore`
            instance pointing at the live store path.
        review_queue_root: Optional override for the review-queue store
            location; resolved via :func:`resolve_review_queue_root`.
        window_end: Right edge of the measurement window.
        window_days: Width of the window in days.
        min_samples: Minimum sample size before the baseline is
            considered usable for non-placeholder threshold derivation.
        revert_window_days: Days within which a revert counts as
            invalidation; reserved for future settlement-receipt
            schema use.
    """
    if window_days <= 0:
        raise ValueError("window_days must be positive")
    window_end = _ensure_utc(window_end)

    # Auto-handle side --------------------------------------------------
    auto_invalidations = list(
        iter_invalidations_from_calibration_store(
            calibration_store,
            window_end=window_end,
            window_days=window_days,
        )
    )
    auto_total = _count_calibration_decisions_in_window(
        calibration_store,
        window_end=window_end,
        window_days=window_days,
    )

    # Human-settled side ------------------------------------------------
    human_invalidations = list(
        iter_invalidations_from_settlement_receipts(
            store_root=review_queue_root,
            revert_window_days=revert_window_days,
        )
    )
    # Only count human invalidations whose settled_at falls in the
    # window; iter_invalidations_from_settlement_receipts() emits all
    # of them regardless of date because the schema does not yet have
    # post-settlement signals to filter on.
    window_start = window_end - timedelta(days=window_days)
    human_invalidations_in_window = [
        d for d in human_invalidations if window_start <= d.settled_at <= window_end
    ]

    human_total = count_decisions_from_settlement_receipts(
        store_root=review_queue_root,
        window_end=window_end,
        window_days=window_days,
    )

    measurement = compute_baseline(
        list(auto_invalidations) + human_invalidations_in_window,
        total_human_settled=human_total,
        total_auto_handled=auto_total,
        window_end=window_end,
        window_days=window_days,
        min_samples=min_samples,
    )

    # Tag the gap explicitly so downstream consumers don't mistake a
    # zero numerator for a measured zero rate. The note distinguishes the
    # two failure modes:
    #   - schema_gap_human_numerator: receipts in the window do not carry the
    #     v2 outcome_* fields at all (i.e. observe_outcome has not yet run on
    #     any of them); the schema can hold the signals but the data has not
    #     been collected.
    #   - schema_v1_only: receipts in the window have only legacy v1 fields
    #     (reverted_at / post_merge_incident / redo_pr); kept for backwards
    #     compatibility but no v2-shaped data is available.
    extra_notes = dict(measurement.notes)
    if human_total:
        v2_observed_count = _count_receipts_with_v2_outcome_fields(
            store_root=review_queue_root,
            window_end=window_end,
            window_days=window_days,
        )
        coverage = (
            "complete"
            if v2_observed_count == human_total
            else "partial"
            if v2_observed_count
            else "absent"
        )
        extra_notes.setdefault("human_invalidations_coverage", coverage)
        extra_notes.setdefault("human_invalidations_observed_count", str(v2_observed_count))
        extra_notes.setdefault("human_settlement_receipt_count", str(human_total))
        if coverage == "complete" and not human_invalidations_in_window:
            extra_notes.setdefault(
                "human_invalidations_source",
                "settlement-receipt schema-v2 outcome fields are present on all "
                "receipts in the window, but no receipt in the window "
                "fired any of the five canonical signals. Treat as measured "
                "zero because the human invalidation observation coverage is complete.",
            )
        elif coverage != "complete" and not human_invalidations_in_window:
            extra_notes.setdefault(
                "human_invalidations_source",
                f"schema_gap_human_numerator: settlement-receipt v2 outcome "
                f"fields are populated on {v2_observed_count}/{human_total} "
                "receipts in the window. Run "
                "aragora.review.settlement_outcome.observe_outcome over the "
                "window to close this gap. Until then, human-side numerator "
                "is partial data availability, not a full-window measurement.",
            )

    # Re-pack to attach the additional note while keeping the
    # measurement immutable in spirit. BaselineMeasurement is frozen,
    # so we re-construct rather than mutating.
    return BaselineMeasurement(
        window_start=measurement.window_start,
        window_end=measurement.window_end,
        window_days=measurement.window_days,
        total_human_settled=measurement.total_human_settled,
        invalidated_human_settled=measurement.invalidated_human_settled,
        total_auto_handled=measurement.total_auto_handled,
        invalidated_auto_handled=measurement.invalidated_auto_handled,
        baseline_human_rate=measurement.baseline_human_rate,
        baseline_human_rate_ci_low=measurement.baseline_human_rate_ci_low,
        baseline_human_rate_ci_high=measurement.baseline_human_rate_ci_high,
        auto_handle_rate=measurement.auto_handle_rate,
        auto_handle_rate_ci_low=measurement.auto_handle_rate_ci_low,
        auto_handle_rate_ci_high=measurement.auto_handle_rate_ci_high,
        per_class_human=measurement.per_class_human,
        per_class_auto=measurement.per_class_auto,
        min_samples_required=measurement.min_samples_required,
        sample_size_acceptable=measurement.sample_size_acceptable,
        notes=extra_notes,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_rows(
    store: AutoHandleCalibrationStore,
    query: str,
    params: Iterable[Any],
) -> list[sqlite3.Row]:
    """Run ``query`` against the store's connection and return all rows.

    Read-only; does not open a write transaction. Uses the store's
    ``_connection`` context manager so the file-vs-memory connection
    lifecycle stays consistent with the rest of the calibration code.
    """
    # ``_connection`` is module-private but documented as the
    # canonical way to get a configured connection within the
    # calibration package; using it here keeps WAL / busy-timeout /
    # row-factory configuration identical to writers and avoids the
    # journal-mode mismatch flagged in the calibration module
    # docstring.
    with store._connection() as conn:  # intentional in-package read
        rows = conn.execute(query, tuple(params)).fetchall()
    return list(rows)


def _count_calibration_decisions_in_window(
    store: AutoHandleCalibrationStore,
    *,
    window_end: datetime,
    window_days: int,
) -> int:
    """Count auto-handled decisions in the window (success + failures)."""
    end_ts = window_end.timestamp()
    start_ts = end_ts - (window_days * 86400)
    rows = _read_rows(
        store,
        "SELECT COUNT(*) AS n FROM auto_handle_decisions "
        "WHERE outcome IN (?, ?, ?, ?) AND decided_at >= ? AND decided_at <= ?",
        [
            OUTCOME_SUCCESS,
            OUTCOME_REVERT,
            OUTCOME_INCIDENT,
            OUTCOME_HUMAN_OVERRIDE,
            float(start_ts),
            float(end_ts),
        ],
    )
    if not rows:
        return 0
    return int(rows[0]["n"] or 0)


def _invalidation_from_calibration_row(row: sqlite3.Row) -> InvalidatedDecision | None:
    """Build an :class:`InvalidatedDecision` from one calibration-store row.

    Returns ``None`` when the outcome string is not recognized as a
    failure (for example, a future-schema outcome we don't yet know
    how to map). The caller will see the row simply skipped.
    """
    outcome = str(row["outcome"] or "")
    if outcome not in _FAILURE_OUTCOMES:
        return None
    signal = _OUTCOME_TO_SIGNAL[outcome]
    decided_at = float(row["decided_at"] or 0.0)
    settled_at = datetime.fromtimestamp(decided_at, tz=UTC)
    pr_url = str(row["pr_url"] or "").strip()
    decision_class = str(row["decision_class"] or "").strip()
    rationale = (
        f"calibration-store outcome={outcome!r} (class={decision_class!r}, pr_url={pr_url!r})"
    )
    return InvalidatedDecision(
        decision_id=str(row["decision_id"] or ""),
        settled_at=settled_at,
        signals=(signal,),
        rationales=(rationale,),
        was_human_settled=False,
        was_auto_handled=True,
    )


def _invalidation_from_settlement_receipt(
    payload: dict[str, Any],
    *,
    source_path: Path | None = None,
    revert_window_days: int = DEFAULT_REVERT_WINDOW_DAYS,
) -> InvalidatedDecision | None:
    """Build an :class:`InvalidatedDecision` from one settlement-receipt dict.

    Today's schema does not carry post-settlement signals, so this
    function returns ``None`` for almost every receipt. It is structured
    so that adding new fields (e.g. ``reverted_at``,
    ``post_merge_incident``, ``redo_pr``) becomes a small additive
    change inside this function rather than reshaping every caller.

    Args:
        payload: Parsed JSON of one settlement-receipt file.
        source_path: Optional path for logging diagnostics.
        revert_window_days: Days within which a recorded revert counts.
    """
    reviewed_at_raw = payload.get("reviewed_at")
    pr_number = payload.get("pr_number")
    action = payload.get("action")
    if not reviewed_at_raw or pr_number is None or not action:
        return None
    try:
        settled_at = _parse_iso(str(reviewed_at_raw))
    except ValueError:
        logger.warning(
            "review.invalidation_event_source: receipt %s has invalid reviewed_at=%r",
            source_path,
            reviewed_at_raw,
        )
        return None

    signals: list[str] = []
    rationales: list[str] = []

    # Schema v2 fields (#6375 phase 4) — explicit boolean signals populated by
    # ``aragora.review.settlement_outcome.observe_outcome``. ``None`` means
    # "not yet observed"; ``True`` means signal fired; ``False`` means signal
    # was checked and did not fire.
    v2_revert = payload.get("outcome_revert_within_window")
    v2_incident = payload.get("outcome_post_merge_incident")
    v2_redo = payload.get("outcome_human_override_redo")
    v2_rollback = payload.get("outcome_rollback")
    v2_reopened = payload.get("outcome_reopened_pr")

    if v2_revert is True:
        signals.append(INVALIDATION_REVERT_WITHIN_WINDOW)
        rationales.append("settlement-receipt outcome_revert_within_window=True")
    if v2_incident is True:
        signals.append(INVALIDATION_POST_MERGE_INCIDENT)
        rationales.append("settlement-receipt outcome_post_merge_incident=True")
    if v2_redo is True:
        signals.append(INVALIDATION_HUMAN_OVERRIDE_REDO)
        rationales.append("settlement-receipt outcome_human_override_redo=True")
    if v2_rollback is True:
        signals.append(INVALIDATION_ROLLBACK)
        rationales.append("settlement-receipt outcome_rollback=True")
    if v2_reopened is True:
        signals.append(INVALIDATION_REOPENED_PR)
        rationales.append("settlement-receipt outcome_reopened_pr=True")

    # Schema v1 fields — kept for backwards compatibility with receipts that
    # carry the older field names. Defensive lookups: continue working when
    # receipt schemas grow without breaking.
    reverted_at_raw = payload.get("reverted_at")
    incident_attributed = bool(payload.get("post_merge_incident"))
    redo_pr = payload.get("redo_pr") or payload.get("human_override_redo_pr")

    if reverted_at_raw and v2_revert is None and INVALIDATION_REVERT_WITHIN_WINDOW not in signals:
        try:
            reverted_at = _parse_iso(str(reverted_at_raw))
        except ValueError:
            reverted_at = None
        if reverted_at is not None:
            delta = reverted_at - settled_at
            if timedelta(0) <= delta <= timedelta(days=revert_window_days):
                signals.append(INVALIDATION_REVERT_WITHIN_WINDOW)
                rationales.append(
                    f"settlement-receipt records revert {delta.days}d after settlement "
                    f"(window={revert_window_days}d)"
                )

    if (
        incident_attributed
        and v2_incident is None
        and INVALIDATION_POST_MERGE_INCIDENT not in signals
    ):
        signals.append(INVALIDATION_POST_MERGE_INCIDENT)
        rationales.append("settlement-receipt records post_merge_incident attributed to this PR")

    if redo_pr and v2_redo is None and INVALIDATION_HUMAN_OVERRIDE_REDO not in signals:
        signals.append(INVALIDATION_HUMAN_OVERRIDE_REDO)
        rationales.append(f"settlement-receipt references follow-up redo PR {redo_pr!r}")

    if not signals:
        return None

    session_id = str(payload.get("session_id") or "")
    decision_id = f"pr-{pr_number}-{session_id}-{action}"

    return InvalidatedDecision(
        decision_id=decision_id,
        settled_at=settled_at,
        signals=tuple(signals),
        rationales=tuple(rationales),
        was_human_settled=True,
        was_auto_handled=False,
    )


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("review.invalidation_event_source: could not read %s: %s", path, exc)
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("review.invalidation_event_source: malformed JSON in %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        logger.warning("review.invalidation_event_source: non-dict payload in %s", path)
        return None
    return data


def _ensure_utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts


def _parse_iso(raw: str) -> datetime:
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
