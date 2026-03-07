"""Tests for receipt-backed CLI inbox review."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from aragora.inbox.cli_review import CLIReviewLoop
from aragora.inbox.trust_wedge import InboxWedgeAction, ReceiptState, TriageDecision


def _make_decision() -> TriageDecision:
    return TriageDecision.create(
        final_action="ignore",
        confidence=0.4,
        dissent_summary="",
        receipt_id="receipt-1",
    )


def _make_envelope(
    decision: TriageDecision,
    *,
    action: str,
    state: ReceiptState,
):
    updated = TriageDecision.create(
        final_action=action,
        confidence=decision.confidence,
        dissent_summary=decision.dissent_summary,
        receipt_id=decision.receipt_id,
        auto_approval_eligible=state is ReceiptState.APPROVED,
        receipt_state=state.value,
        intent=decision.intent,
        provider_route=decision.provider_route,
        label_id=decision.label_id,
        blocked_by_policy=decision.blocked_by_policy,
    )
    return SimpleNamespace(
        intent=decision.intent,
        decision=updated,
        receipt=SimpleNamespace(receipt_id=decision.receipt_id, state=state),
    )


def test_review_batch_uses_receipt_review_for_approve():
    decision = _make_decision()
    review_fn = MagicMock(
        return_value=_make_envelope(decision, action="ignore", state=ReceiptState.APPROVED)
    )

    loop = CLIReviewLoop(
        input_fn=lambda _prompt: "a",
        print_fn=lambda *_args, **_kwargs: None,
        review_fn=review_fn,
    )

    results = loop.review_batch([decision])

    review_fn.assert_called_once_with(
        "receipt-1",
        choice="approve",
        edited_action=None,
        edited_rationale=None,
        label_id=None,
    )
    assert results[0]["action_taken"] == "approve"
    assert decision.receipt_state == ReceiptState.APPROVED.value


def test_review_batch_uses_receipt_review_for_edit():
    decision = _make_decision()
    answers = iter(["e", "archive"])
    review_fn = MagicMock(
        return_value=_make_envelope(decision, action="archive", state=ReceiptState.CREATED)
    )

    loop = CLIReviewLoop(
        input_fn=lambda _prompt: next(answers),
        print_fn=lambda *_args, **_kwargs: None,
        review_fn=review_fn,
    )

    results = loop.review_batch([decision])

    review_fn.assert_called_once_with(
        "receipt-1",
        choice="edit",
        edited_action="archive",
        edited_rationale=None,
        label_id=None,
    )
    assert results[0]["action_taken"] == "edit"
    assert decision.final_action == InboxWedgeAction.ARCHIVE
    assert decision.receipt_state == ReceiptState.CREATED.value
