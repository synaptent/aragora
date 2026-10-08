"""The settlement review-due listener records an audit event."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from aragora.debate import settlement_event_listener
from aragora.observability import audit_log


def test_due_settlement_is_written_to_the_audit_log(monkeypatch) -> None:
    sink = MagicMock()
    monkeypatch.setattr(audit_log, "get_audit_log", lambda: sink)
    event = SimpleNamespace(
        debate_id="debate-7",
        confidence=0.8,
        falsifier_count=2,
        settled_at="2026-01-01T00:00:00Z",
        review_horizon="2026-02-01T00:00:00Z",
    )

    settlement_event_listener._log_due_settlement(event)

    sink.log.assert_called_once()
    recorded = sink.log.call_args.args[0]
    assert recorded.category is audit_log.AuditCategory.DEBATE
    assert (recorded.action, recorded.resource_type, recorded.resource_id) == (
        "settlement_review_due",
        "debate",
        "debate-7",
    )
    assert recorded.details["falsifier_count"] == 2
