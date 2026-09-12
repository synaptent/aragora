"""Tests for receipt list/show CLI convergence on the durable store."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import ModuleType
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from aragora.cli.commands.receipt import (
    _format_receipt_created_at,
    cmd_receipt_export,
    cmd_receipt_list,
    cmd_receipt_show,
)


@dataclass
class _StoredReceiptStub:
    receipt_id: str
    gauntlet_id: str
    verdict: str
    confidence: float
    created_at: float
    data: dict = field(default_factory=dict)

    def to_full_dict(self) -> dict:
        payload = dict(self.data)
        payload.setdefault("receipt_id", self.receipt_id)
        payload.setdefault("gauntlet_id", self.gauntlet_id)
        payload.setdefault("verdict", self.verdict)
        payload.setdefault("confidence", self.confidence)
        return payload


def test_receipt_list_reads_durable_store_by_default(capsys: pytest.CaptureFixture[str]) -> None:
    stored = _StoredReceiptStub(
        receipt_id="rcpt-quickstart-123",
        gauntlet_id="rcpt-quickstart-123",
        verdict="PASS",
        confidence=1.0,
        created_at=1711300000.0,
        data={"risk_summary": {"total": 2}},
    )
    durable_store = MagicMock()
    durable_store.list.return_value = [stored]

    with patch("aragora.cli.commands.receipt._load_storage_receipt_list", return_value=[stored]):
        with patch("aragora.cli.commands.receipt._load_legacy_receipt_list") as legacy_loader:
            cmd_receipt_list(argparse.Namespace(limit=5, verdict=None, kind=None, org_id=None))

    output = capsys.readouterr().out
    assert "rcpt-quickstart-123" in output
    assert "rcpt-quickst.." not in output
    assert "decision" in output
    assert "PASS" in output
    assert "2" in output
    legacy_loader.assert_not_called()


def test_receipt_list_falls_back_to_legacy_when_durable_empty(
    capsys: pytest.CaptureFixture[str],
) -> None:
    legacy_row = SimpleNamespace(
        gauntlet_id="gauntlet-legacy-123",
        verdict="FAIL",
        confidence=0.25,
        total_findings=4,
        created_at=datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc),
    )

    with patch("aragora.cli.commands.receipt._load_storage_receipt_list", return_value=[]):
        with patch(
            "aragora.cli.commands.receipt._load_legacy_receipt_list",
            return_value=[legacy_row],
        ):
            cmd_receipt_list(argparse.Namespace(limit=5, verdict="fail", kind=None, org_id=None))

    output = capsys.readouterr().out
    assert "gauntlet-legacy-123" in output
    assert "gauntlet-leg.." not in output
    assert "other" in output
    assert "FAIL" in output
    assert "4" in output


def test_receipt_list_normalizes_trust_wedge_receipts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stored = _StoredReceiptStub(
        receipt_id="rcpt-triage-123",
        gauntlet_id="rcpt-triage-123",
        verdict="UNKNOWN",
        confidence=0.0,
        created_at=1711300000.0,
        data={
            "state": "CREATED",
            "triage_decision": {
                "confidence": 0.73,
                "blocked_by_policy": True,
            },
        },
    )

    with patch("aragora.cli.commands.receipt._load_storage_receipt_list", return_value=[stored]):
        cmd_receipt_list(argparse.Namespace(limit=5, verdict=None, kind=None, org_id=None))

    output = capsys.readouterr().out
    assert "inbox" in output
    assert "BLOCKED" in output
    assert "73%" in output


def test_receipt_list_filters_by_kind(capsys: pytest.CaptureFixture[str]) -> None:
    inbox = _StoredReceiptStub(
        receipt_id="rcpt-inbox-123",
        gauntlet_id="rcpt-inbox-123",
        verdict="CONDITIONAL",
        confidence=0.95,
        created_at=1711300000.0,
        data={"action_intent": {}, "triage_decision": {}},
    )
    decision = _StoredReceiptStub(
        receipt_id="rcpt-decision-456",
        gauntlet_id="rcpt-decision-456",
        verdict="PASS",
        confidence=0.85,
        created_at=1711300001.0,
        data={"consensus_proof": {}, "agent_responses": []},
    )

    with patch(
        "aragora.cli.commands.receipt._load_storage_receipt_list",
        return_value=[inbox, decision],
    ):
        cmd_receipt_list(argparse.Namespace(limit=5, verdict=None, kind="inbox", org_id=None))

    output = capsys.readouterr().out
    assert "rcpt-inbox-123" in output
    assert "inbox" in output
    assert "rcpt-decision-456" not in output


def test_receipt_list_prints_full_id_never_truncated(capsys: pytest.CaptureFixture[str]) -> None:
    """Regression test for #9985: the table must print the full id, not a

    12-char-plus-".." shortened form that cannot be fed back to `receipt show`
    or `receipt export`.
    """
    long_id = "rcpt-" + "f" * 40
    stored = _StoredReceiptStub(
        receipt_id=long_id,
        gauntlet_id=long_id,
        verdict="PASS",
        confidence=1.0,
        created_at=1711300000.0,
        data={"risk_summary": {"total": 0}},
    )

    with patch("aragora.cli.commands.receipt._load_storage_receipt_list", return_value=[stored]):
        cmd_receipt_list(argparse.Namespace(limit=5, verdict=None, kind=None, org_id=None))

    output = capsys.readouterr().out
    assert long_id in output
    assert ".." not in output


def test_receipt_list_json_emits_full_ids(capsys: pytest.CaptureFixture[str]) -> None:
    long_id = "rcpt-" + "a" * 40
    stored = _StoredReceiptStub(
        receipt_id=long_id,
        gauntlet_id=long_id,
        verdict="PASS",
        confidence=0.9,
        created_at=1711300000.0,
        data={"risk_summary": {"total": 3}},
    )

    with patch("aragora.cli.commands.receipt._load_storage_receipt_list", return_value=[stored]):
        cmd_receipt_list(
            argparse.Namespace(limit=5, verdict=None, kind=None, org_id=None, json=True)
        )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["id"] == long_id
    assert payload[0]["type"] == "decision"
    assert payload[0]["verdict"] == "PASS"
    assert payload[0]["findings"] == 3


def test_receipt_list_id_round_trips_to_show_and_export(tmp_path) -> None:
    """End-to-end regression test for #9985.

    Creates a receipt in a real (temp-file) receipt store, runs `receipt list`
    against it, and feeds the exact id `list` printed back into `receipt show
    --format json` and `receipt export --format odr` — both must exit 0 (i.e.
    not call sys.exit) rather than reporting "receipt not found".
    """
    from aragora.storage.receipt_store import ReceiptStore, set_receipt_store

    long_id = "rcpt-" + "b" * 40
    store = ReceiptStore(db_path=tmp_path / "receipts.db", file_receipt_dirs=[])
    try:
        set_receipt_store(store)
        store.save(
            {
                "receipt_id": long_id,
                "gauntlet_id": long_id,
                "timestamp": "2026-03-24T12:00:00+00:00",
                "verdict": "PASS",
                "confidence": 0.9,
                "risk_level": "LOW",
                "risk_score": 0.1,
                "checksum": "deadbeef",
                "risk_summary": {"total": 0},
            }
        )

        import io
        from contextlib import redirect_stdout

        list_out = io.StringIO()
        with redirect_stdout(list_out):
            cmd_receipt_list(argparse.Namespace(limit=5, verdict=None, kind=None, org_id=None))
        list_output = list_out.getvalue()
        assert long_id in list_output

        # Extract the id exactly as printed (first column) and feed it back.
        printed_id = next(line.split()[0] for line in list_output.splitlines() if long_id in line)
        assert printed_id == long_id

        show_out = io.StringIO()
        with redirect_stdout(show_out):
            cmd_receipt_show(argparse.Namespace(id=printed_id, format="json", org_id=None))
        show_payload = json.loads(show_out.getvalue())
        assert show_payload["receipt_id"] == long_id

        export_out = io.StringIO()
        with redirect_stdout(export_out):
            cmd_receipt_export(argparse.Namespace(receipt=printed_id, format="odr", output=None))
        assert export_out.getvalue().strip()
    finally:
        set_receipt_store(None)


def test_receipt_created_at_formats_epoch_and_iso_consistently() -> None:
    iso_timestamp = "2026-03-30T18:47:29.647269+00:00"
    epoch_timestamp = datetime.fromisoformat(iso_timestamp).timestamp()

    assert _format_receipt_created_at(epoch_timestamp) == _format_receipt_created_at(iso_timestamp)


def test_receipt_show_reads_durable_store_by_receipt_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stored = _StoredReceiptStub(
        receipt_id="rcpt-live-123",
        gauntlet_id="rcpt-live-123",
        verdict="PASS",
        confidence=1.0,
        created_at=1711300000.0,
        data={"summary": "Stored in durable receipt store"},
    )

    with patch(
        "aragora.cli.commands.receipt._load_storage_receipt", return_value=stored.to_full_dict()
    ):
        with patch("aragora.cli.commands.receipt._load_legacy_receipt") as legacy_loader:
            cmd_receipt_show(argparse.Namespace(id="rcpt-live-123", format="json", org_id=None))

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["receipt_id"] == "rcpt-live-123"
    assert payload["summary"] == "Stored in durable receipt store"
    legacy_loader.assert_not_called()


def test_receipt_show_normalizes_trust_wedge_receipts_for_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stored = {
        "receipt_id": "rcpt-triage-456",
        "gauntlet_id": "rcpt-triage-456",
        "verdict": "UNKNOWN",
        "confidence": 0.0,
        "state": "CREATED",
        "triage_decision": {
            "confidence": 0.61,
            "blocked_by_policy": True,
        },
    }

    with patch("aragora.cli.commands.receipt._load_storage_receipt", return_value=stored):
        cmd_receipt_show(argparse.Namespace(id="rcpt-triage-456", format="json", org_id=None))

    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "BLOCKED"
    assert payload["confidence"] == pytest.approx(0.61)


def test_receipt_show_clamps_out_of_range_decision_confidence_for_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stored = {
        "receipt_id": "rcpt-decision-999",
        "gauntlet_id": "rcpt-decision-999",
        "verdict": "PASS",
        "confidence": 1.2,
        "consensus_proof": {
            "reached": True,
            "confidence": 1.4,
        },
    }

    with patch("aragora.cli.commands.receipt._load_storage_receipt", return_value=stored):
        cmd_receipt_show(argparse.Namespace(id="rcpt-decision-999", format="json", org_id=None))

    payload = json.loads(capsys.readouterr().out)
    assert payload["confidence"] == pytest.approx(1.0)
    assert payload["consensus_proof"]["confidence"] == pytest.approx(1.0)


def test_receipt_show_renders_inbox_receipt_details(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stored = {
        "receipt_id": "rcpt-inbox-789",
        "gauntlet_id": "rcpt-inbox-789",
        "verdict": "CONDITIONAL",
        "confidence": 0.95,
        "state": "created",
        "action_intent": {
            "provider": "gmail",
            "message_id": "msg-123",
            "action": "archive",
            "provider_route": "direct",
            "synthesized_rationale": "Archive the newsletter.",
        },
        "triage_decision": {
            "final_action": "archive",
            "provider_route": "direct",
            "receipt_state": "created",
            "blocked_by_policy": False,
        },
    }

    with patch("aragora.cli.commands.receipt._load_storage_receipt", return_value=stored):
        cmd_receipt_show(argparse.Namespace(id="rcpt-inbox-789", format=None, org_id=None))

    output = capsys.readouterr().out
    assert "Type:          inbox" in output
    assert "Action:        archive" in output
    assert "Provider:      gmail" in output
    assert "Message ID:    msg-123" in output
    assert "Receipt State: created" in output
    assert "Rationale:     Archive the newsletter." in output


def test_receipt_show_accepts_markdown_format_alias(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stored = {
        "receipt_id": "rcpt-markdown-123",
        "gauntlet_id": "rcpt-markdown-123",
        "verdict": "PASS",
        "confidence": 1.0,
    }
    fake_module = ModuleType("aragora.gauntlet.receipt_models")

    class _FakeDecisionReceipt:
        @staticmethod
        def from_dict(data: dict) -> SimpleNamespace:
            return SimpleNamespace(to_markdown=lambda: "# receipt")

    fake_module.DecisionReceipt = _FakeDecisionReceipt

    with patch("aragora.cli.commands.receipt._load_storage_receipt", return_value=stored):
        with patch.dict("sys.modules", {"aragora.gauntlet.receipt_models": fake_module}):
            cmd_receipt_show(
                argparse.Namespace(id="rcpt-markdown-123", format="markdown", org_id=None)
            )

    assert capsys.readouterr().out.strip() == "# receipt"


def test_receipt_show_falls_back_to_legacy_when_durable_missing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    legacy_data = {
        "receipt_id": "legacy-rcpt-456",
        "gauntlet_id": "gauntlet-live-456",
        "verdict": "CONDITIONAL",
        "confidence": 0.6,
    }

    with patch("aragora.cli.commands.receipt._load_storage_receipt", return_value=None):
        with patch(
            "aragora.cli.commands.receipt._load_legacy_receipt",
            return_value=legacy_data,
        ):
            cmd_receipt_show(argparse.Namespace(id="gauntlet-live-456", format="json", org_id=None))

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["receipt_id"] == "legacy-rcpt-456"
    assert payload["gauntlet_id"] == "gauntlet-live-456"
