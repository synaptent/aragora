"""Tests for the triage CLI command wiring."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from aragora.cli.commands import triage as triage_cmd
from aragora.inbox.trust_wedge import InboxWedgeAction, TriageDecision


@pytest.mark.asyncio
async def test_run_triage_uses_receipt_review_loop():
    decision = TriageDecision.create(
        final_action="ignore",
        confidence=0.4,
        dissent_summary="",
        receipt_id="receipt-1",
    )
    fake_runner = SimpleNamespace(run_triage=AsyncMock(return_value=[decision]))
    fake_service = SimpleNamespace(review_receipt=object())
    captured: dict[str, object] = {}

    class _FakeLoop:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def review_batch(self, decisions):
            captured["decisions"] = decisions
            return []

    with (
        patch.object(triage_cmd, "_get_gmail_connector", return_value=object()),
        patch(
            "aragora.inbox.triage_runner.InboxTriageRunner",
            return_value=fake_runner,
        ),
        patch(
            "aragora.inbox.trust_wedge.get_inbox_trust_wedge_service",
            return_value=fake_service,
        ),
        patch(
            "aragora.inbox.cli_review.CLIReviewLoop",
            _FakeLoop,
        ),
    ):
        await triage_cmd._run_triage(batch_size=1, auto_approve=False)

    assert captured["review_fn"] is fake_service.review_receipt
    assert captured["decisions"] == [decision]


def test_print_decisions_formats_enum_values(capsys):
    decision = TriageDecision.create(
        final_action=InboxWedgeAction.IGNORE,
        confidence=0.4,
        dissent_summary="",
        receipt_id="receipt-1",
    )
    decision.intent = SimpleNamespace(_subject="Subject line")

    triage_cmd._print_decisions([decision])

    out = capsys.readouterr().out
    assert "ignore" in out
    assert "InboxWedgeAction" not in out
