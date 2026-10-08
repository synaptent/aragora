"""The receipt delivery task sends only receipts the acting org owns.

A real SQLite ``ReceiptStore`` holds ``RCA`` (org A), ``RCB`` (org B) and
``RCN`` (no owner). ``deliver_receipt_for_org`` runs with a captured Slack
channel standing in for the notifier. Acting for org A it must send nothing
and record nothing for ``RCB``, ``RCN`` or an unknown id, and for ``RCA`` it
must send exactly once and record the delivery against org A.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from aragora.notifications.models import (
    Notification,
    NotificationChannel,
    NotificationResult,
    SlackConfig,
)
from aragora.notifications.providers import SlackProvider
from aragora.notifications.receipt_delivery import deliver_receipt_for_org
from aragora.notifications.service import NotificationService
from aragora.server.handlers.utils import receipt_delivery_history
from aragora.server.handlers.utils.receipt_delivery_history import DELIVERY_ORG_KEY
from aragora.storage.receipt_store import ReceiptStore

ORG_A = "org-a"
ORG_B = "org-b"
CHANNEL = "#receipts-a"


def _receipt(receipt_id: str) -> dict[str, Any]:
    return {
        "receipt_id": receipt_id,
        "gauntlet_id": f"g-{receipt_id}",
        "debate_id": f"debate-{receipt_id}",
        "timestamp": "2026-10-01T12:00:00+00:00",
        "verdict": "PASS",
        "confidence": 0.9,
        "robustness_score": 0.8,
        "risk_summary": {"critical": 0, "high": 1, "medium": 0, "low": 2},
        "input_summary": f"secret question of {receipt_id}",
    }


class _CapturedSlack(SlackProvider):
    def __init__(self, sent: list[tuple[str, Notification]]) -> None:
        super().__init__(SlackConfig(webhook_url="https://slack.invalid/hook"))
        self._sent = sent

    async def send(self, notification: Notification, recipient: str) -> NotificationResult:
        self._sent.append((recipient, notification))
        return NotificationResult(
            success=True,
            channel=NotificationChannel.SLACK,
            recipient=recipient,
            notification_id=notification.id,
            external_id="ts-1",
        )


@pytest.fixture
def store(tmp_path) -> ReceiptStore:
    store = ReceiptStore(db_path=tmp_path / "receipts.db", file_receipt_dirs=[])
    store.save(_receipt("RCA"), org_id=ORG_A, created_by="user-a")
    store.save(_receipt("RCB"), org_id=ORG_B, created_by="user-b")
    store.save(_receipt("RCN"))
    return store


@pytest.fixture
def history(monkeypatch) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    monkeypatch.setattr(receipt_delivery_history, "_receipt_delivery_history", entries)
    return entries


@pytest.fixture
def sent() -> list[tuple[str, Notification]]:
    captured: list[tuple[str, Notification]] = []
    service = NotificationService(enable_circuit_breakers=False)
    service.providers = {NotificationChannel.SLACK: _CapturedSlack(captured)}
    with patch(
        "aragora.notifications.receipt_delivery.get_notification_service", return_value=service
    ):
        yield captured


async def _deliver(store: ReceiptStore, org_id: str | None, receipt_id: str):
    return await deliver_receipt_for_org(
        org_id, receipt_id, ["slack"], [], slack_channel=CHANNEL, store=store
    )


class TestDeliveryTaskActsOnlyForTheOwningOrg:
    @pytest.mark.parametrize("receipt_id", ["RCB", "RCN", "RC-missing"])
    @pytest.mark.asyncio
    async def test_receipt_not_owned_by_the_org_is_not_sent_or_recorded(
        self, store, sent, history, receipt_id
    ):
        results = await _deliver(store, ORG_A, receipt_id)

        assert results == []
        assert sent == []
        assert history == []

    @pytest.mark.parametrize("org_id", [None, "", "   "])
    @pytest.mark.asyncio
    async def test_task_without_an_org_sends_nothing(self, store, sent, history, org_id):
        results = await _deliver(store, org_id, "RCA")

        assert results == []
        assert sent == []
        assert history == []

    @pytest.mark.asyncio
    async def test_own_receipt_is_sent_once_and_recorded_for_the_org(self, store, sent, history):
        results = await _deliver(store, ORG_A, "RCA")

        captured = [
            {"recipient": recipient, "resource_id": n.resource_id, "org_id": n.org_id}
            for recipient, n in sent
        ]
        print("captured sends:", captured)
        print("recorded deliveries:", [(e["receipt_id"], e[DELIVERY_ORG_KEY]) for e in history])
        assert captured == [{"recipient": CHANNEL, "resource_id": "RCA", "org_id": ORG_A}]
        assert [(r.success, r.receipt_id, r.org_id) for r in results] == [(True, "RCA", ORG_A)]
        assert [(e["receipt_id"], e["status"], e[DELIVERY_ORG_KEY]) for e in history] == [
            ("RCA", "success", ORG_A)
        ]

    @pytest.mark.asyncio
    async def test_payload_naming_another_receipt_is_sent_as_the_stored_row(
        self, store, sent, history
    ):
        store._backend.execute_write(
            "UPDATE receipts SET data_json = ? WHERE receipt_id = ?",
            ('{"receipt_id": "RCB", "verdict": "PASS"}', "RCA"),
        )

        await _deliver(store, ORG_A, "RCA")

        assert [n.resource_id for _r, n in sent] == ["RCA"]
        assert [e["receipt_id"] for e in history] == ["RCA"]
