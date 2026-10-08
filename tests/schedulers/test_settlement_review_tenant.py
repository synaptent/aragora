"""The settlement review scheduler acts on each receipt only within its own org.

A real SQLite ``ReceiptStore`` holds due settlement receipts of org A, org B
and one with no owner. The scheduler must review each org's receipts with that
org's id, never apply one org's context to another org's receipt, and leave
receipts with no owning org untouched.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from aragora.scheduler.settlement_resolvers import get_settlement_resolver_registry
from aragora.scheduler.settlement_review import SettlementReviewScheduler
from aragora.storage.receipt_store import ReceiptStore

ORG_A = "org-a"
ORG_B = "org-b"


def _due_receipt(receipt_id: str) -> dict[str, Any]:
    old = datetime.now(timezone.utc) - timedelta(days=40)
    return {
        "receipt_id": receipt_id,
        "gauntlet_id": f"g-{receipt_id}",
        "debate_id": f"debate-{receipt_id}",
        "timestamp": old.isoformat(),
        "verdict": "PASS",
        "confidence": 0.8,
        "mode": "epistemic_hygiene",
        "agents_involved": [f"agent-of-{receipt_id}"],
        "settlement": {
            "status": "pending_human_adjudication",
            "resolver_type": "human",
            "human_outcome": True,
            "review_horizon_days": 30,
            "claim": f"claim of {receipt_id}",
        },
    }


class _RecordingResolvers:
    """Delegates to the real resolver registry and records which receipt each call concerns."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._registry = get_settlement_resolver_registry()

    def resolve(self, resolver_type: str, **kwargs: Any) -> Any:
        self.calls.append(kwargs["receipt_data"]["receipt_id"])
        return self._registry.resolve(resolver_type, **kwargs)


@pytest.fixture
def store(tmp_path) -> ReceiptStore:
    store = ReceiptStore(db_path=tmp_path / "receipts.db", file_receipt_dirs=[])
    store.save(_due_receipt("rcpt-a1"), org_id=ORG_A, created_by="user-a")
    store.save(_due_receipt("rcpt-a2"), org_id=ORG_A, created_by="user-a")
    store.save(_due_receipt("rcpt-b1"), org_id=ORG_B, created_by="user-b")
    store.save(_due_receipt("rcpt-null"))
    return store


def _run(store: ReceiptStore, **scheduler_kwargs: Any):
    recorded = MagicMock(wraps=store)
    scheduler = SettlementReviewScheduler(recorded, **scheduler_kwargs)
    tracker = MagicMock()
    resolvers = _RecordingResolvers()
    scheduler._calibration_tracker = tracker
    scheduler._resolver_registry = resolvers
    counts = scheduler._review_due_receipts_sync()
    return counts, recorded, tracker, resolvers


def _saves(recorded: MagicMock) -> list[tuple[str, str | None]]:
    return [(c.args[0]["receipt_id"], c.kwargs.get("org_id")) for c in recorded.save.call_args_list]


class TestSettlementReviewPerTenant:
    def test_every_action_carries_the_receipts_own_org(self, store):
        counts, recorded, tracker, resolvers = _run(store, max_receipts_per_run=50)

        saves = _saves(recorded)
        print("captured saves:", saves)
        assert sorted(saves) == [
            ("rcpt-a1", ORG_A),
            ("rcpt-a2", ORG_A),
            ("rcpt-b1", ORG_B),
        ]
        for receipt_id, org_id in saves:
            assert store.get(receipt_id).org_id == org_id
        assert sorted(resolvers.calls) == ["rcpt-a1", "rcpt-a2", "rcpt-b1"]
        predictions = sorted(
            (c.kwargs["agent"], c.kwargs["debate_id"]) for c in tracker.record_prediction.mock_calls
        )
        assert predictions == [
            ("agent-of-rcpt-a1", "debate-rcpt-a1"),
            ("agent-of-rcpt-a2", "debate-rcpt-a2"),
            ("agent-of-rcpt-b1", "debate-rcpt-b1"),
        ]
        assert counts == (3, 3, 3, 3, 0)

    def test_each_org_is_read_with_its_own_filtered_query(self, store):
        _counts, recorded, _tracker, _resolvers = _run(store, max_receipts_per_run=50)

        recorded.list.assert_not_called()
        queried = sorted({c.args[0] for c in recorded.list_for_org.call_args_list})
        assert queried == [ORG_A, ORG_B]

    def test_unowned_receipt_is_never_read_or_changed(self, store):
        before = store.get("rcpt-null")

        _counts, recorded, tracker, resolvers = _run(store, max_receipts_per_run=50)

        after = store.get("rcpt-null")
        assert "rcpt-null" not in {receipt_id for receipt_id, _ in _saves(recorded)}
        assert "rcpt-null" not in resolvers.calls
        assert all(
            c.kwargs["debate_id"] != "debate-rcpt-null"
            for c in tracker.record_prediction.mock_calls
        )
        assert after.org_id is None
        assert after.data["settlement"] == before.data["settlement"]
        assert "last_reviewed_at" not in after.data["settlement"]

    def test_settled_receipts_keep_their_owner(self, store):
        _run(store, max_receipts_per_run=50)

        for receipt_id, org_id in (("rcpt-a1", ORG_A), ("rcpt-b1", ORG_B)):
            stored = store.get(receipt_id)
            assert stored.org_id == org_id
            assert stored.data["settlement"]["status"] == "settled_true"

    def test_payload_naming_another_receipt_cannot_overwrite_it(self, store):
        hijack = _due_receipt("rcpt-b1")
        hijack["gauntlet_id"] = "g-rcpt-a1"
        hijack["settlement"]["claim"] = "written while reviewing org A"
        store._backend.execute_write(
            "UPDATE receipts SET data_json = ? WHERE receipt_id = ?",
            (json.dumps(hijack), "rcpt-a1"),
        )

        _counts, recorded, _tracker, _resolvers = _run(store, max_receipts_per_run=50)

        assert store.get("rcpt-b1").data["settlement"]["claim"] == "claim of rcpt-b1"
        assert store.get("rcpt-b1").org_id == ORG_B
        assert ("rcpt-b1", ORG_A) not in _saves(recorded)
        assert ("rcpt-a1", ORG_A) in _saves(recorded)

    def test_receipt_cap_applies_per_org_so_no_org_starves(self, store):
        _counts, recorded, _tracker, _resolvers = _run(store, max_receipts_per_run=1)

        saved_orgs = sorted(org_id for _receipt_id, org_id in _saves(recorded))
        assert saved_orgs == [ORG_A, ORG_B]


class TestReceiptStoreOwnerOrgs:
    def test_lists_each_owning_org_once_and_never_an_empty_owner(self, store):
        store.save(_due_receipt("rcpt-blank"))
        store._backend.execute_write(
            "UPDATE receipts SET org_id = '' WHERE receipt_id = ?", ("rcpt-blank",)
        )

        assert store.list_owner_org_ids() == [ORG_A, ORG_B]
