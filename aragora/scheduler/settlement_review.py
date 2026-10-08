"""
Settlement review scheduler for epistemic hygiene debate receipts.

The scheduler periodically scans receipts with settlement metadata, checks
whether they are due for review, updates settlement status, and records
calibration outcomes when settlement outcomes become available.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.storage.receipt_store import ReceiptStore
    from aragora.scheduler.settlement_resolvers import SettlementResolverRegistry

logger = logging.getLogger(__name__)

DEFAULT_REVIEW_INTERVAL_HOURS = int(
    os.environ.get("ARAGORA_SETTLEMENT_REVIEW_INTERVAL_HOURS", "24")
)
DEFAULT_MAX_RECEIPTS_PER_RUN = int(os.environ.get("ARAGORA_SETTLEMENT_REVIEW_MAX_RECEIPTS", "500"))
DEFAULT_STARTUP_DELAY_SECONDS = int(
    os.environ.get("ARAGORA_SETTLEMENT_REVIEW_STARTUP_DELAY_SECONDS", "60")
)

_TERMINAL_SETTLEMENT_STATUSES = {"settled_true", "settled_false", "settled_inconclusive"}
_OUTCOME_TRUE_STRINGS = {"true", "correct", "confirmed", "success", "succeeded", "pass", "yes"}
_OUTCOME_FALSE_STRINGS = {"false", "incorrect", "falsified", "failure", "failed", "no"}
_EPISTEMIC_HYGIENE_MODE = "epistemic_hygiene"
_ALLOWED_RESOLVER_TYPES = {"human", "deterministic", "oracle"}
_RESOLVER_ALIASES = {
    "manual": "human",
    "reviewer": "human",
    "ci": "deterministic",
    "test": "deterministic",
    "auto": "deterministic",
    "onchain": "oracle",
    "feed": "oracle",
}


def _coerce_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _resolve_settlement_outcome(settlement: dict[str, Any]) -> bool | None:
    """Resolve explicit settlement outcome into a correctness boolean if available."""
    status_raw = str(settlement.get("status") or "").strip().lower()
    if status_raw in {"settled_true", "confirmed", "correct"}:
        return True
    if status_raw in {"settled_false", "falsified", "incorrect"}:
        return False
    if status_raw in {"settled_inconclusive", "inconclusive"}:
        return None

    for field_name in ("outcome", "result", "resolved_outcome"):
        value = settlement.get(field_name)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in _OUTCOME_TRUE_STRINGS:
                return True
            if normalized in _OUTCOME_FALSE_STRINGS:
                return False
    return None


def _is_terminal_status(status: str) -> bool:
    return status.strip().lower() in _TERMINAL_SETTLEMENT_STATUSES


def _normalize_resolver_type(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    normalized = _RESOLVER_ALIASES.get(normalized, normalized)
    if normalized in _ALLOWED_RESOLVER_TYPES:
        return normalized
    return None


def _record_calibration_outcome_metric(outcome: str) -> None:
    try:
        from aragora.observability.metrics.settlement import record_calibration_outcome

        record_calibration_outcome(outcome)
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        logger.debug("Failed to emit calibration outcome metric", exc_info=True)


def _compute_due_at(receipt_timestamp: datetime, settlement: dict[str, Any]) -> datetime:
    explicit_next = _parse_timestamp(settlement.get("next_review_at"))
    if explicit_next is not None:
        return explicit_next
    horizon_days = _coerce_positive_int(settlement.get("review_horizon_days"), default=30)
    return receipt_timestamp + timedelta(days=horizon_days)


@dataclass
class SettlementReviewResult:
    """Result summary for one settlement review cycle."""

    receipts_scanned: int
    receipts_due: int
    receipts_updated: int
    calibration_predictions_recorded: int
    unresolved_due: int
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipts_scanned": self.receipts_scanned,
            "receipts_due": self.receipts_due,
            "receipts_updated": self.receipts_updated,
            "calibration_predictions_recorded": self.calibration_predictions_recorded,
            "unresolved_due": self.unresolved_due,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "success": self.error is None,
            "error": self.error,
        }


@dataclass
class SettlementReviewStats:
    """Cumulative settlement review scheduler stats."""

    total_runs: int = 0
    total_receipts_scanned: int = 0
    total_receipts_updated: int = 0
    total_calibration_predictions: int = 0
    failures: int = 0
    last_run: datetime | None = None
    last_result: SettlementReviewResult | None = None
    results: list[SettlementReviewResult] = field(default_factory=list)

    def add_result(self, result: SettlementReviewResult) -> None:
        self.total_runs += 1
        if result.error:
            self.failures += 1
        self.total_receipts_scanned += result.receipts_scanned
        self.total_receipts_updated += result.receipts_updated
        self.total_calibration_predictions += result.calibration_predictions_recorded
        self.last_run = result.completed_at
        self.last_result = result
        self.results.append(result)
        if len(self.results) > 100:
            self.results = self.results[-100:]

    def to_dict(self) -> dict[str, Any]:
        success_rate = (
            (self.total_runs - self.failures) / self.total_runs if self.total_runs > 0 else 1.0
        )
        return {
            "total_runs": self.total_runs,
            "total_receipts_scanned": self.total_receipts_scanned,
            "total_receipts_updated": self.total_receipts_updated,
            "total_calibration_predictions": self.total_calibration_predictions,
            "failures": self.failures,
            "success_rate": success_rate,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "last_result": self.last_result.to_dict() if self.last_result else None,
        }


class SettlementReviewScheduler:
    """Periodically reviews settlement metadata and updates calibration."""

    def __init__(
        self,
        store: ReceiptStore,  # noqa: F821 - forward reference
        *,
        interval_hours: int = DEFAULT_REVIEW_INTERVAL_HOURS,
        max_receipts_per_run: int = DEFAULT_MAX_RECEIPTS_PER_RUN,
        startup_delay_seconds: int = DEFAULT_STARTUP_DELAY_SECONDS,
        on_review_complete: Callable[[SettlementReviewResult], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        self.store = store
        self.interval_hours = interval_hours
        self.max_receipts_per_run = max_receipts_per_run
        self.startup_delay_seconds = startup_delay_seconds
        self.on_review_complete = on_review_complete
        self.on_error = on_error

        self._task: asyncio.Task | None = None
        self._running = False
        self._stats = SettlementReviewStats()
        self._calibration_tracker: Any | None = None
        self._resolver_registry: SettlementResolverRegistry | None = None

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    @property
    def stats(self) -> SettlementReviewStats:
        return self._stats

    async def start(self) -> None:
        if self.is_running:
            logger.warning("Settlement review scheduler is already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._review_loop())
        logger.info(
            "Started settlement review scheduler (interval=%sh, max_receipts=%s)",
            self.interval_hours,
            self.max_receipts_per_run,
        )

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Stopped settlement review scheduler")

    async def _review_loop(self) -> None:
        await asyncio.sleep(max(0, self.startup_delay_seconds))
        while self._running:
            try:
                result = await self.review_due_receipts()
                self._stats.add_result(result)
                if result.error:
                    logger.warning("Settlement review completed with error: %s", result.error)
                elif result.receipts_updated > 0:
                    logger.info(
                        "Settlement review updated %s due receipts (calibration predictions=%s)",
                        result.receipts_updated,
                        result.calibration_predictions_recorded,
                    )
                else:
                    logger.debug("Settlement review completed: no due settlement updates")
                if self.on_review_complete:
                    try:
                        self.on_review_complete(result)
                    except (TypeError, ValueError, RuntimeError) as exc:
                        logger.error("Error in settlement review callback: %s", exc)
            except (ConnectionError, TimeoutError, OSError, RuntimeError, ValueError) as exc:
                logger.error("Error in settlement review cycle: %s", exc, exc_info=True)
                if self.on_error:
                    try:
                        self.on_error(exc)
                    except (TypeError, ValueError, RuntimeError) as callback_exc:
                        logger.error("Error in settlement review error callback: %s", callback_exc)
            await asyncio.sleep(self.interval_hours * 3600)

    async def review_due_receipts(self) -> SettlementReviewResult:
        started_at = datetime.now(timezone.utc)
        loop = asyncio.get_running_loop()
        try:
            result_tuple = await loop.run_in_executor(None, self._review_due_receipts_sync)
            (
                receipts_scanned,
                receipts_due,
                receipts_updated,
                calibration_predictions_recorded,
                unresolved_due,
            ) = result_tuple
            error = None
        except (ConnectionError, TimeoutError, OSError, RuntimeError, ValueError) as exc:
            logger.error("Settlement review run failed: %s", exc)
            receipts_scanned = 0
            receipts_due = 0
            receipts_updated = 0
            calibration_predictions_recorded = 0
            unresolved_due = 0
            error = "settlement review failed"
        completed_at = datetime.now(timezone.utc)
        duration = (completed_at - started_at).total_seconds()
        return SettlementReviewResult(
            receipts_scanned=receipts_scanned,
            receipts_due=receipts_due,
            receipts_updated=receipts_updated,
            calibration_predictions_recorded=calibration_predictions_recorded,
            unresolved_due=unresolved_due,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration,
            error=error,
        )

    def _get_calibration_tracker(self):
        if self._calibration_tracker is None:
            from aragora.agents.calibration import CalibrationTracker

            self._calibration_tracker = CalibrationTracker()
        return self._calibration_tracker

    def _get_resolver_registry(self):
        if self._resolver_registry is None:
            from aragora.scheduler.settlement_resolvers import get_settlement_resolver_registry

            self._resolver_registry = get_settlement_resolver_registry()
        return self._resolver_registry

    def _review_due_receipts_sync(self) -> tuple[int, int, int, int, int]:
        """Review due settlements tenant by tenant.

        Each owning org is read through its own org-filtered query and gets its
        own ``max_receipts_per_run`` budget, so a large org cannot starve the
        others. Receipts with no owning org are never read or changed.
        """
        now = datetime.now(timezone.utc)
        totals = [0, 0, 0, 0, 0]
        for org_id in self.store.list_owner_org_ids():
            for index, value in enumerate(self._review_org_receipts(org_id, now)):
                totals[index] += value
        scanned, due, updated, calibration_predictions, unresolved_due = totals
        return scanned, due, updated, calibration_predictions, unresolved_due

    def _review_org_receipts(self, org_id: str, now: datetime) -> tuple[int, int, int, int, int]:
        scanned = 0
        due = 0
        updated = 0
        calibration_predictions = 0
        unresolved_due = 0

        offset = 0
        while scanned < self.max_receipts_per_run:
            batch_limit = min(100, self.max_receipts_per_run - scanned)
            batch = self.store.list_for_org(org_id, limit=batch_limit, offset=offset, order="desc")
            if not batch:
                break

            for stored in batch:
                scanned += 1
                if stored.org_id != org_id or not stored.receipt_id:
                    continue
                review = self._review_receipt(stored, now)
                if review is None:
                    continue
                data, predictions, unresolved = review
                due += 1
                calibration_predictions += predictions
                unresolved_due += int(unresolved)
                self.store.save(data, org_id=org_id, created_by=stored.created_by)
                updated += 1

            offset += len(batch)

        return scanned, due, updated, calibration_predictions, unresolved_due

    def _review_receipt(
        self, stored: Any, now: datetime
    ) -> tuple[dict[str, Any], int, bool] | None:
        """Review one stored receipt; None when it has no settlement due.

        Returns the updated payload, the calibration predictions recorded and
        whether the settlement is still unresolved.
        """
        data = dict(stored.data or {})
        # The update is written back by receipt_id; pin it to the stored row so
        # a payload naming another receipt cannot overwrite that receipt.
        data["receipt_id"] = stored.receipt_id
        settlement = data.get("settlement")
        if not isinstance(settlement, dict):
            return None

        # Derive receipt timestamp for review horizon computation.
        receipt_timestamp = (
            _parse_timestamp(data.get("timestamp"))
            or _parse_timestamp(settlement.get("created_at"))
            or datetime.fromtimestamp(stored.created_at, tz=timezone.utc)
        )

        due_at = _compute_due_at(receipt_timestamp, settlement)
        if now < due_at:
            return None

        calibration_predictions = 0
        review_attempts = _coerce_positive_int(settlement.get("review_attempts"), default=0)
        settlement["review_attempts"] = review_attempts + 1
        settlement["last_reviewed_at"] = now.isoformat()

        prior_status = str(settlement.get("status") or "").strip().lower()
        resolver_type = _normalize_resolver_type(
            settlement.get("resolver_type")
            or settlement.get("resolution_tier")
            or settlement.get("verification_mode")
        )
        if resolver_type is not None:
            settlement["resolver_type"] = resolver_type
        outcome = _resolve_settlement_outcome(settlement)
        if outcome is None and resolver_type is not None:
            decision = self._get_resolver_registry().resolve(
                resolver_type,
                receipt_data=data,
                settlement=settlement,
                now=now,
            )
            settlement["last_resolution_attempt"] = decision.to_dict()
            if decision.resolved and decision.outcome is not None:
                outcome = bool(decision.outcome)
                settlement["outcome"] = outcome
                settlement["resolved_outcome"] = outcome
                settlement["resolved_by"] = decision.resolver_id
                settlement["resolution_evidence"] = decision.evidence

        if outcome is None:
            if not _is_terminal_status(prior_status):
                if resolver_type == "human":
                    settlement["status"] = "pending_human_adjudication"
                elif resolver_type == "deterministic":
                    settlement["status"] = "pending_deterministic"
                elif resolver_type == "oracle":
                    settlement["status"] = "pending_oracle"
                else:
                    settlement["status"] = "pending_outcome"
            horizon_days = _coerce_positive_int(settlement.get("review_horizon_days"), default=30)
            settlement["next_review_at"] = (now + timedelta(days=horizon_days)).isoformat()
        else:
            settlement["status"] = "settled_true" if outcome else "settled_false"
            settlement["settled_at"] = settlement.get("settled_at") or now.isoformat()
            settlement["next_review_at"] = None
            if not settlement.get("calibration_recorded_at"):
                mode = str(data.get("mode") or "").strip().lower()

                if mode != _EPISTEMIC_HYGIENE_MODE:
                    settlement["calibration_recorded_at"] = now.isoformat()
                    settlement["calibration_outcome"] = "skipped_non_epistemic_mode"
                    _record_calibration_outcome_metric("skipped_non_epistemic_mode")
                elif resolver_type is None:
                    if not settlement.get("calibration_pending_since"):
                        settlement["calibration_pending_since"] = now.isoformat()
                    if settlement.get("calibration_outcome") != "pending_resolver_verification":
                        _record_calibration_outcome_metric("pending_resolver_verification")
                    settlement["calibration_outcome"] = "pending_resolver_verification"
                    horizon_days = _coerce_positive_int(
                        settlement.get("review_horizon_days"), default=30
                    )
                    settlement["next_review_at"] = (now + timedelta(days=horizon_days)).isoformat()
                else:
                    confidence = max(0.0, min(1.0, float(data.get("confidence") or 0.5)))
                    domain = _EPISTEMIC_HYGIENE_MODE
                    debate_id = str(data.get("debate_id") or stored.debate_id or "")
                    tracker = self._get_calibration_tracker()
                    recorded_agents = 0
                    for agent in data.get("agents_involved") or []:
                        if not isinstance(agent, str) or not agent.strip():
                            continue
                        tracker.record_prediction(
                            agent=agent.strip(),
                            confidence=confidence,
                            correct=outcome,
                            domain=domain,
                            debate_id=debate_id,
                            prediction_type="settlement_review",
                        )
                        calibration_predictions += 1
                        recorded_agents += 1
                    settlement["calibration_recorded_at"] = now.isoformat()
                    if recorded_agents > 0:
                        settlement["calibration_outcome"] = "correct" if outcome else "incorrect"
                        _record_calibration_outcome_metric("correct" if outcome else "incorrect")
                        settlement["calibration_resolver_type"] = resolver_type
                    else:
                        settlement["calibration_outcome"] = "skipped_no_agents"
                        _record_calibration_outcome_metric("skipped_no_agents")

        data["settlement"] = settlement
        return data, calibration_predictions, outcome is None

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self.is_running,
            "interval_hours": self.interval_hours,
            "max_receipts_per_run": self.max_receipts_per_run,
            "startup_delay_seconds": self.startup_delay_seconds,
            "stats": self._stats.to_dict(),
        }


_scheduler: SettlementReviewScheduler | None = None


def get_settlement_review_scheduler(
    store: ReceiptStore | None = None,  # noqa: F821
) -> SettlementReviewScheduler | None:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    if store is None:
        return None
    _scheduler = SettlementReviewScheduler(store)
    return _scheduler


def set_settlement_review_scheduler(scheduler: SettlementReviewScheduler | None) -> None:
    global _scheduler
    _scheduler = scheduler


__all__ = [
    "SettlementReviewResult",
    "SettlementReviewStats",
    "SettlementReviewScheduler",
    "get_settlement_review_scheduler",
    "set_settlement_review_scheduler",
]
