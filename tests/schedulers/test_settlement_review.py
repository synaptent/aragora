"""Tests for settlement review scheduler."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from aragora.scheduler.settlement_review import (
    SettlementReviewScheduler,
    get_settlement_review_scheduler,
    set_settlement_review_scheduler,
)


@dataclass
class _StoredReceiptStub:
    data: dict
    created_at: float
    debate_id: str | None = None
    org_id: str | None = None
    created_by: str | None = None


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


class _InMemoryReceiptStore:
    """Simple in-memory store that matches settlement scheduler list/save expectations."""

    def __init__(self) -> None:
        self._items: list[_StoredReceiptStub] = []

    def list(self, *, limit: int, offset: int, order: str = "desc") -> list[_StoredReceiptStub]:
        items = self._items[::-1] if order == "desc" else self._items[:]
        return items[offset : offset + limit]

    def save(self, data: dict, *, org_id: str | None = None, created_by: str | None = None) -> str:
        receipt_id = str(data.get("receipt_id") or "")
        debate_id = str(data.get("debate_id") or "") or None
        timestamp_raw = data.get("timestamp")
        if isinstance(timestamp_raw, str):
            normalized = (
                timestamp_raw[:-1] + "+00:00" if timestamp_raw.endswith("Z") else timestamp_raw
            )
            try:
                created_at = datetime.fromisoformat(normalized).timestamp()
            except ValueError:
                created_at = datetime.now(timezone.utc).timestamp()
        else:
            created_at = datetime.now(timezone.utc).timestamp()

        payload = copy.deepcopy(data)
        for idx, existing in enumerate(self._items):
            if str(existing.data.get("receipt_id") or "") == receipt_id:
                self._items[idx] = _StoredReceiptStub(
                    data=payload,
                    created_at=existing.created_at,
                    debate_id=debate_id or existing.debate_id,
                    org_id=existing.org_id or org_id,
                    created_by=existing.created_by or created_by,
                )
                return receipt_id

        self._items.append(
            _StoredReceiptStub(
                data=payload,
                created_at=created_at,
                debate_id=debate_id,
                org_id=org_id,
                created_by=created_by,
            )
        )
        return receipt_id

    def latest(self) -> _StoredReceiptStub:
        if not self._items:
            raise AssertionError("Store is empty")
        return self._items[-1]


class TestSettlementReviewScheduler:
    def teardown_method(self) -> None:
        set_settlement_review_scheduler(None)

    def test_review_marks_due_unresolved_receipt_pending(self) -> None:
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=35)
        receipt = _StoredReceiptStub(
            data={
                "receipt_id": "r1",
                "gauntlet_id": "debate-r1",
                "debate_id": "debate-r1",
                "timestamp": _iso(old),
                "confidence": 0.62,
                "mode": "epistemic_hygiene",
                "agents_involved": ["claude"],
                "settlement": {
                    "status": "needs_definition",
                    "review_horizon_days": 30,
                    "falsifier": "KPI misses threshold",
                    "metric": "KPI >= 95%",
                    "claim": "Decision improves KPI",
                },
            },
            created_at=old.timestamp(),
            debate_id="debate-r1",
        )

        store = MagicMock()
        store.list.side_effect = [[receipt], []]
        store.save = MagicMock()

        scheduler = SettlementReviewScheduler(store, max_receipts_per_run=10)
        (
            scanned,
            due,
            updated,
            calibration_predictions,
            unresolved_due,
        ) = scheduler._review_due_receipts_sync()

        assert scanned == 1
        assert due == 1
        assert updated == 1
        assert calibration_predictions == 0
        assert unresolved_due == 1
        saved = store.save.call_args[0][0]
        settlement = saved["settlement"]
        assert settlement["status"] == "pending_outcome"
        assert settlement["review_attempts"] == 1
        assert isinstance(settlement.get("next_review_at"), str)

    def test_review_routes_unresolved_human_settlements_to_human_pending(self) -> None:
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=35)
        receipt = _StoredReceiptStub(
            data={
                "receipt_id": "r1b",
                "gauntlet_id": "debate-r1b",
                "debate_id": "debate-r1b",
                "timestamp": _iso(old),
                "confidence": 0.62,
                "mode": "epistemic_hygiene",
                "agents_involved": ["claude"],
                "settlement": {
                    "status": "open",
                    "resolver_type": "human",
                    "review_horizon_days": 30,
                    "falsifier": "KPI misses threshold",
                    "metric": "KPI >= 95%",
                    "claim": "Decision improves KPI",
                },
            },
            created_at=old.timestamp(),
            debate_id="debate-r1b",
        )
        store = MagicMock()
        store.list.side_effect = [[receipt], []]
        store.save = MagicMock()

        scheduler = SettlementReviewScheduler(store, max_receipts_per_run=10)
        (
            _scanned,
            _due,
            _updated,
            calibration_predictions,
            unresolved_due,
        ) = scheduler._review_due_receipts_sync()

        assert calibration_predictions == 0
        assert unresolved_due == 1
        saved = store.save.call_args[0][0]
        settlement = saved["settlement"]
        assert settlement["status"] == "pending_human_adjudication"
        assert settlement["last_resolution_attempt"]["reason"] == "waiting_for_human_adjudication"

    def test_review_auto_settles_deterministic_resolver(self) -> None:
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=40)
        receipt = _StoredReceiptStub(
            data={
                "receipt_id": "r2det",
                "gauntlet_id": "debate-r2det",
                "debate_id": "debate-r2det",
                "timestamp": _iso(old),
                "confidence": 0.81,
                "mode": "epistemic_hygiene",
                "agents_involved": ["claude", "gpt-5"],
                "settlement": {
                    "status": "pending_deterministic",
                    "resolver_type": "deterministic",
                    "deterministic_rule": {
                        "observed": 0.03,
                        "operator": "<=",
                        "target": 0.05,
                    },
                    "review_horizon_days": 30,
                    "falsifier": "Error budget breached",
                    "metric": "Error budget consumption < 5%",
                    "claim": "Plan reduces incidents",
                },
            },
            created_at=old.timestamp(),
            debate_id="debate-r2det",
        )

        store = MagicMock()
        store.list.side_effect = [[receipt], []]
        store.save = MagicMock()
        scheduler = SettlementReviewScheduler(store, max_receipts_per_run=10)
        tracker = MagicMock()
        scheduler._calibration_tracker = tracker

        (
            _scanned,
            _due,
            _updated,
            calibration_predictions,
            unresolved_due,
        ) = scheduler._review_due_receipts_sync()

        assert calibration_predictions == 2
        assert unresolved_due == 0
        assert tracker.record_prediction.call_count == 2
        saved = store.save.call_args[0][0]
        settlement = saved["settlement"]
        assert settlement["status"] == "settled_true"
        assert settlement["calibration_outcome"] == "correct"
        assert settlement["calibration_resolver_type"] == "deterministic"
        assert settlement["last_resolution_attempt"]["reason"] == "deterministic_rule_evaluated"
        assert settlement["resolved_by"] == "deterministic_rule_engine"

    def test_review_auto_settles_oracle_resolver(self, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=40)
        monkeypatch.setenv("ARAGORA_ORACLE_HMAC_SECRET", "test-secret")
        signed_at = now.isoformat()
        canonical = json.dumps(
            {"outcome": False, "source": "oracle-feed-A", "signed_at": signed_at},
            sort_keys=True,
            separators=(",", ":"),
        )
        signature = hmac.new(
            b"test-secret",
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        receipt = _StoredReceiptStub(
            data={
                "receipt_id": "r2or",
                "gauntlet_id": "debate-r2or",
                "debate_id": "debate-r2or",
                "timestamp": _iso(old),
                "confidence": 0.81,
                "mode": "epistemic_hygiene",
                "agents_involved": ["claude", "gpt-5"],
                "settlement": {
                    "status": "pending_oracle",
                    "resolver_type": "oracle",
                    "oracle_attestation": {
                        "outcome": False,
                        "source": "oracle-feed-A",
                        "signed_at": signed_at,
                        "signature": signature,
                    },
                    "review_horizon_days": 30,
                    "falsifier": "Error budget breached",
                    "metric": "Error budget consumption < 5%",
                    "claim": "Plan reduces incidents",
                },
            },
            created_at=old.timestamp(),
            debate_id="debate-r2or",
        )

        store = MagicMock()
        store.list.side_effect = [[receipt], []]
        store.save = MagicMock()
        scheduler = SettlementReviewScheduler(store, max_receipts_per_run=10)
        tracker = MagicMock()
        scheduler._calibration_tracker = tracker

        (
            _scanned,
            _due,
            _updated,
            calibration_predictions,
            unresolved_due,
        ) = scheduler._review_due_receipts_sync()

        assert calibration_predictions == 2
        assert unresolved_due == 0
        assert tracker.record_prediction.call_count == 2
        saved = store.save.call_args[0][0]
        settlement = saved["settlement"]
        assert settlement["status"] == "settled_false"
        assert settlement["calibration_outcome"] == "incorrect"
        assert settlement["calibration_resolver_type"] == "oracle"
        assert settlement["last_resolution_attempt"]["reason"] == "oracle_attestation_verified"
        assert settlement["resolved_by"] == "signed_oracle_attestation"

    def test_review_records_calibration_for_settled_outcome(self) -> None:
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=40)
        receipt = _StoredReceiptStub(
            data={
                "receipt_id": "r2",
                "gauntlet_id": "debate-r2",
                "debate_id": "debate-r2",
                "timestamp": _iso(old),
                "confidence": 0.81,
                "mode": "epistemic_hygiene",
                "agents_involved": ["claude", "gpt-5"],
                "settlement": {
                    "status": "pending_outcome",
                    "outcome": True,
                    "resolver_type": "human",
                    "review_horizon_days": 30,
                    "falsifier": "Error budget breached",
                    "metric": "Error budget consumption < 5%",
                    "claim": "Plan reduces incidents",
                },
            },
            created_at=old.timestamp(),
            debate_id="debate-r2",
        )

        store = MagicMock()
        store.list.side_effect = [[receipt], []]
        store.save = MagicMock()

        scheduler = SettlementReviewScheduler(store, max_receipts_per_run=10)
        tracker = MagicMock()
        scheduler._calibration_tracker = tracker
        (
            scanned,
            due,
            updated,
            calibration_predictions,
            unresolved_due,
        ) = scheduler._review_due_receipts_sync()

        assert scanned == 1
        assert due == 1
        assert updated == 1
        assert calibration_predictions == 2
        assert unresolved_due == 0
        assert tracker.record_prediction.call_count == 2
        saved = store.save.call_args[0][0]
        settlement = saved["settlement"]
        assert settlement["status"] == "settled_true"
        assert settlement["calibration_outcome"] == "correct"
        assert settlement["calibration_resolver_type"] == "human"
        assert isinstance(settlement.get("calibration_recorded_at"), str)

    def test_review_skips_calibration_for_non_epistemic_mode(self) -> None:
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=40)
        receipt = _StoredReceiptStub(
            data={
                "receipt_id": "r2b",
                "gauntlet_id": "debate-r2b",
                "debate_id": "debate-r2b",
                "timestamp": _iso(old),
                "confidence": 0.81,
                "mode": "general",
                "agents_involved": ["claude", "gpt-5"],
                "settlement": {
                    "status": "pending_outcome",
                    "outcome": True,
                    "resolver_type": "human",
                    "review_horizon_days": 30,
                    "falsifier": "Error budget breached",
                    "metric": "Error budget consumption < 5%",
                    "claim": "Plan reduces incidents",
                },
            },
            created_at=old.timestamp(),
            debate_id="debate-r2b",
        )

        store = MagicMock()
        store.list.side_effect = [[receipt], []]
        store.save = MagicMock()

        scheduler = SettlementReviewScheduler(store, max_receipts_per_run=10)
        tracker = MagicMock()
        scheduler._calibration_tracker = tracker
        (
            _scanned,
            _due,
            _updated,
            calibration_predictions,
            _unresolved_due,
        ) = scheduler._review_due_receipts_sync()

        assert calibration_predictions == 0
        tracker.record_prediction.assert_not_called()
        saved = store.save.call_args[0][0]
        settlement = saved["settlement"]
        assert settlement["status"] == "settled_true"
        assert settlement["calibration_outcome"] == "skipped_non_epistemic_mode"
        assert isinstance(settlement.get("calibration_recorded_at"), str)

    def test_review_defers_calibration_without_verified_resolver(self) -> None:
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=40)
        receipt = _StoredReceiptStub(
            data={
                "receipt_id": "r2c",
                "gauntlet_id": "debate-r2c",
                "debate_id": "debate-r2c",
                "timestamp": _iso(old),
                "confidence": 0.81,
                "mode": "epistemic_hygiene",
                "agents_involved": ["claude", "gpt-5"],
                "settlement": {
                    "status": "pending_outcome",
                    "outcome": True,
                    "resolver_type": "tribunal",
                    "review_horizon_days": 7,
                    "falsifier": "Error budget breached",
                    "metric": "Error budget consumption < 5%",
                    "claim": "Plan reduces incidents",
                },
            },
            created_at=old.timestamp(),
            debate_id="debate-r2c",
        )

        store = MagicMock()
        store.list.side_effect = [[receipt], []]
        store.save = MagicMock()

        scheduler = SettlementReviewScheduler(store, max_receipts_per_run=10)
        tracker = MagicMock()
        scheduler._calibration_tracker = tracker
        (
            _scanned,
            _due,
            _updated,
            calibration_predictions,
            _unresolved_due,
        ) = scheduler._review_due_receipts_sync()

        assert calibration_predictions == 0
        tracker.record_prediction.assert_not_called()
        saved = store.save.call_args[0][0]
        settlement = saved["settlement"]
        assert settlement["status"] == "settled_true"
        assert settlement["calibration_outcome"] == "pending_resolver_verification"
        assert settlement.get("calibration_recorded_at") is None
        assert isinstance(settlement.get("next_review_at"), str)
        assert isinstance(settlement.get("calibration_pending_since"), str)

    def test_review_skips_not_due_receipts(self) -> None:
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        receipt = _StoredReceiptStub(
            data={
                "receipt_id": "r3",
                "gauntlet_id": "debate-r3",
                "debate_id": "debate-r3",
                "timestamp": _iso(recent),
                "settlement": {
                    "status": "needs_definition",
                    "review_horizon_days": 30,
                    "falsifier": "Target misses threshold",
                    "metric": "Target > baseline",
                    "claim": "Change has positive effect",
                },
            },
            created_at=recent.timestamp(),
            debate_id="debate-r3",
        )
        store = MagicMock()
        store.list.side_effect = [[receipt], []]
        store.save = MagicMock()

        scheduler = SettlementReviewScheduler(store, max_receipts_per_run=10)
        (
            scanned,
            due,
            updated,
            calibration_predictions,
            unresolved_due,
        ) = scheduler._review_due_receipts_sync()

        assert scanned == 1
        assert due == 0
        assert updated == 0
        assert calibration_predictions == 0
        assert unresolved_due == 0
        store.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_stop_scheduler(self) -> None:
        store = MagicMock()
        store.list.return_value = []
        scheduler = SettlementReviewScheduler(
            store,
            interval_hours=1,
            startup_delay_seconds=0,
            max_receipts_per_run=10,
        )

        assert not scheduler.is_running
        await scheduler.start()
        assert scheduler.is_running
        await scheduler.stop()
        assert not scheduler.is_running

    @pytest.mark.asyncio
    async def test_review_due_receipts_handles_exceptions(self) -> None:
        store = MagicMock()
        store.list.side_effect = RuntimeError("boom")
        scheduler = SettlementReviewScheduler(store, max_receipts_per_run=10)

        result = await scheduler.review_due_receipts()
        assert result.error is not None
        assert result.receipts_updated == 0

    def test_end_to_end_receipt_to_settlement_to_calibration(self) -> None:
        """End-to-end reliability flow: receipt generation -> due settlement review -> calibration."""
        from aragora.server.debate_controller import DebateController

        store = _InMemoryReceiptStore()
        controller = DebateController(
            factory=MagicMock(),
            emitter=MagicMock(),
            storage=MagicMock(),
        )

        config = MagicMock()
        config.question = "Should we enable feature flag rollout?"
        config.agents_str = "claude,gpt-5"
        config.rounds = 2
        config.mode = "epistemic_hygiene"
        config.metadata = {
            "mode": "epistemic_hygiene",
            "settlement": {
                "claim": "Feature rollout reduces incident rate.",
                "falsifier": "Incident rate increases by >= 10%.",
                "metric": "incident_rate_30d",
                "review_horizon_days": 1,
            },
        }

        result = MagicMock()
        result.consensus_reached = True
        result.confidence = 0.78
        result.final_answer = "Proceed with guarded rollout."
        result.participants = ["claude", "gpt-5"]

        with patch("aragora.storage.receipt_store.get_receipt_store", return_value=store):
            controller._generate_debate_receipt(
                debate_id="debate-e2e-1",
                config=config,
                result=result,
                duration_seconds=12.0,
            )

        generated = store.latest()
        settlement = generated.data["settlement"]
        assert settlement["status"] == "needs_definition"
        assert generated.data["mode"] == "epistemic_hygiene"

        old = datetime.now(timezone.utc) - timedelta(days=10)
        generated.data["timestamp"] = _iso(old)
        generated.data["settlement"]["status"] = "pending_outcome"
        generated.data["settlement"]["outcome"] = True
        generated.data["settlement"]["review_horizon_days"] = 1
        generated.data["settlement"]["resolver_type"] = "human"
        store.save(generated.data)

        scheduler = SettlementReviewScheduler(store, max_receipts_per_run=10)
        tracker = MagicMock()
        scheduler._calibration_tracker = tracker
        (
            scanned,
            due,
            updated,
            calibration_predictions,
            unresolved_due,
        ) = scheduler._review_due_receipts_sync()

        assert scanned >= 1
        assert due == 1
        assert updated == 1
        assert calibration_predictions == 2
        assert unresolved_due == 0
        assert tracker.record_prediction.call_count == 2

        settled = store.latest().data["settlement"]
        assert settled["status"] == "settled_true"
        assert settled["calibration_outcome"] == "correct"
        assert isinstance(settled.get("calibration_recorded_at"), str)

    @pytest.mark.parametrize(
        "resolver_type,expected_resolver",
        [
            ("human", "human"),
            ("deterministic", "deterministic"),
            ("oracle", "oracle"),
        ],
    )
    def test_end_to_end_settlement_resolver_paths_record_calibration(
        self,
        resolver_type: str,
        expected_resolver: str,
    ) -> None:
        """Resolver path coverage from receipt generation through settlement review."""
        from aragora.server.debate_controller import DebateController

        store = _InMemoryReceiptStore()
        controller = DebateController(
            factory=MagicMock(),
            emitter=MagicMock(),
            storage=MagicMock(),
        )

        config = MagicMock()
        config.question = "Should we enable a staged rollout?"
        config.agents_str = "claude,gpt-5"
        config.rounds = 2
        config.mode = "epistemic_hygiene"
        config.metadata = {
            "mode": "epistemic_hygiene",
            "settlement": {
                "claim": "Staged rollout lowers incident severity.",
                "falsifier": "Incident severity increases by >= 10%.",
                "metric": "incident_severity_30d",
                "review_horizon_days": 1,
                "resolver_type": resolver_type,
            },
        }

        result = MagicMock()
        result.consensus_reached = True
        result.confidence = 0.71
        result.final_answer = "Proceed with staged rollout."
        result.participants = ["claude", "gpt-5"]

        with patch("aragora.storage.receipt_store.get_receipt_store", return_value=store):
            controller._generate_debate_receipt(
                debate_id=f"debate-resolver-{resolver_type}",
                config=config,
                result=result,
                duration_seconds=9.0,
            )

        generated = store.latest()
        generated_settlement = generated.data["settlement"]
        assert generated_settlement["resolver_type"] == expected_resolver

        old = datetime.now(timezone.utc) - timedelta(days=10)
        generated.data["timestamp"] = _iso(old)
        generated.data["settlement"]["status"] = "pending_outcome"
        generated.data["settlement"]["outcome"] = True
        generated.data["settlement"]["review_horizon_days"] = 1
        generated.data["settlement"]["resolver_type"] = resolver_type
        store.save(generated.data)

        scheduler = SettlementReviewScheduler(store, max_receipts_per_run=10)
        tracker = MagicMock()
        scheduler._calibration_tracker = tracker
        (
            scanned,
            due,
            updated,
            calibration_predictions,
            unresolved_due,
        ) = scheduler._review_due_receipts_sync()

        assert scanned >= 1
        assert due == 1
        assert updated == 1
        assert calibration_predictions == 2
        assert unresolved_due == 0
        assert tracker.record_prediction.call_count == 2

        settled = store.latest().data["settlement"]
        assert settled["status"] == "settled_true"
        assert settled["calibration_outcome"] == "correct"
        assert settled["calibration_resolver_type"] == expected_resolver
        assert isinstance(settled.get("calibration_recorded_at"), str)


class TestGlobalSettlementScheduler:
    def teardown_method(self) -> None:
        set_settlement_review_scheduler(None)

    def test_get_scheduler_requires_store_on_first_call(self) -> None:
        set_settlement_review_scheduler(None)
        assert get_settlement_review_scheduler() is None

    def test_get_scheduler_creates_singleton(self) -> None:
        set_settlement_review_scheduler(None)
        store = MagicMock()
        first = get_settlement_review_scheduler(store)
        second = get_settlement_review_scheduler()
        assert first is not None
        assert first is second
