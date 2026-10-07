"""The feedback phase's auto-receipt is owned by the debate's org and creator.

The server path is ``DebateConfig`` -> ``DebateFactory.create_arena`` ->
``ArenaBuilder`` -> ``Arena`` -> ``FeedbackPhase``, with the offline ``demo``
agents; the receipt lands in a real ``ReceiptStore`` on ``tmp_path``.
"""

from __future__ import annotations

import pytest

from aragora.core import DebateResult, Environment
from aragora.debate.debate_state import DebateContext
from aragora.debate.phases.feedback_phase import FeedbackPhase
from aragora.server.debate_factory import DebateConfig, DebateFactory
from aragora.storage.receipt_store import ReceiptStore

TASK = "Design a rate limiter for the billing gateway"


@pytest.fixture
def store(tmp_path, monkeypatch) -> ReceiptStore:
    store = ReceiptStore(db_path=tmp_path / "receipts.db", file_receipt_dirs=[])
    monkeypatch.setattr("aragora.storage.receipt_store.get_receipt_store", lambda: store)
    return store


def _arena(**owner):
    config = DebateConfig(
        question=TASK,
        agents_str="demo,demo",
        rounds=1,
        auto_trim_unavailable=False,
        enable_verticals=False,
        **owner,
    )
    return DebateFactory().create_arena(config, enable_rlm_training=False)


def _finished_debate() -> DebateContext:
    ctx = DebateContext(env=Environment(task=TASK), debate_id="deb-owner-1")
    ctx.result = DebateResult(
        debate_id="deb-owner-1",
        task=TASK,
        final_answer="Use a token bucket per tenant.",
        confidence=0.9,
        consensus_reached=True,
        participants=["demo-1", "demo-2"],
    )
    return ctx


async def _stored_receipt(phase: FeedbackPhase, store: ReceiptStore):
    receipt = await phase._generate_and_post_receipt(_finished_debate())
    assert receipt is not None
    return store.get(receipt.receipt_id)


def test_server_arena_hands_the_debate_owner_to_the_feedback_phase():
    phase = _arena(org_id="org-a", created_by="user-a").feedback_phase

    assert (phase.receipt_org_id, phase.receipt_created_by) == ("org-a", "user-a")
    assert phase.enable_auto_receipt


@pytest.mark.asyncio
async def test_auto_receipt_is_saved_with_the_debate_owner(store):
    phase = FeedbackPhase(
        enable_knowledge_extraction=False,
        receipt_org_id="org-a",
        receipt_created_by="user-a",
    )

    stored = await _stored_receipt(phase, store)

    assert (stored.org_id, stored.created_by) == ("org-a", "user-a")
    assert store.get_for_org(stored.receipt_id, "org-a") is not None
    assert store.get_for_org(stored.receipt_id, "org-b") is None


@pytest.mark.asyncio
async def test_arena_without_an_owner_still_saves_an_unowned_receipt(store):
    phase = _arena().feedback_phase
    phase.enable_knowledge_extraction = False

    stored = await _stored_receipt(phase, store)

    assert (stored.org_id, stored.created_by) == (None, None)
