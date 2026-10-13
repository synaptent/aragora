from __future__ import annotations

import asyncio
import os
import time

import pytest

os.environ.setdefault("ARAGORA_USE_SECRETS_MANAGER", "0")

from aragora.server.fastapi.routes.receipts import get_receipt, list_receipts
from aragora.tenancy.record_scope import OrgScope

_SCOPE = OrgScope(org_id="org-1", user_id="user-1", role="member")


class _SlowReceiptListStore:
    def list_for_org(self, org_id, **kwargs):
        time.sleep(0.2)
        return []

    def count_for_org(self, org_id, **kwargs):
        time.sleep(0.2)
        return 0


class _SlowReceiptGetStore:
    def get_for_org(self, receipt_id: str, org_id: str):
        time.sleep(0.2)
        return {
            "receipt_id": receipt_id,
            "gauntlet_id": "gauntlet-1",
            "timestamp": "2026-03-26T00:00:00Z",
            "verdict": "APPROVED",
            "confidence": 0.9,
            "risk_level": "LOW",
            "risk_score": 0.1,
            "robustness_score": 0.9,
            "findings": [],
            "agents_involved": ["claude"],
            "checksum": "abc123",
            "org_id": org_id,
        }


async def _ticker(duration: float = 0.35) -> int:
    ticks = 0
    start = time.perf_counter()
    while time.perf_counter() - start < duration:
        await asyncio.sleep(0.01)
        ticks += 1
    return ticks


@pytest.mark.asyncio
async def test_list_receipts_does_not_block_event_loop_for_sync_store() -> None:
    task = asyncio.create_task(_ticker())
    await asyncio.sleep(0)

    response = await list_receipts(
        request=None,
        limit=10,
        offset=0,
        verdict=None,
        debate_id=None,
        scope=_SCOPE,
        store=_SlowReceiptListStore(),
    )
    ticks = await task

    assert response.total == 0
    assert response.receipts == []
    assert ticks >= 10


@pytest.mark.asyncio
async def test_get_receipt_does_not_block_event_loop_for_sync_store() -> None:
    task = asyncio.create_task(_ticker())
    await asyncio.sleep(0)

    response = await get_receipt(
        receipt_id="receipt-123",
        scope=_SCOPE,
        store=_SlowReceiptGetStore(),
    )
    ticks = await task

    assert response.receipt_id == "receipt-123"
    assert response.verdict == "APPROVED"
    assert ticks >= 10
