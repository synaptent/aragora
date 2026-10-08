from __future__ import annotations

import argparse
import asyncio
import json
from unittest.mock import patch

from aragora.cli.commands.starter import cmd_starter
from aragora.cli.demo import _run_demo_debate


def test_run_demo_debate_falls_back_without_aragora_debate(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    with patch("aragora.cli.demo.HAS_ARAGORA_DEBATE", False):
        result, elapsed = asyncio.run(_run_demo_debate("Should starter stay offline-safe?"))

    assert elapsed == 0.0
    assert result.consensus is not None
    assert result.receipt is not None
    assert result.receipt.receipt_id.startswith("DR-MOCK-")
    assert result.rounds_used == 2
    assert len(result.proposals) == 4
    assert len(result.votes) == 4
    assert (tmp_path / "aragora-demo-receipt.json").exists()

    captured = capsys.readouterr()
    assert "Mode:   Offline (mock agents, no API keys needed)" in captured.out
    assert "package unavailable" not in captured.out
    assert "DECISION RECEIPT" in captured.out


def test_starter_uses_demo_fallback_when_aragora_debate_is_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    output_path = tmp_path / "starter-receipt.json"
    args = argparse.Namespace(
        question="Should we use a truthful fallback for starter?",
        output=str(output_path),
        no_browser=True,
        skip_init=True,
        demo_name=None,
    )

    with (
        patch("aragora.cli.demo.HAS_ARAGORA_DEBATE", False),
        patch("aragora.cli.commands.starter._detect_api_keys", return_value=[]),
    ):
        cmd_starter(args)

    receipt = json.loads(output_path.read_text())
    assert receipt["question"] == "Should we use a truthful fallback for starter?"
    assert receipt["receipt_id"].startswith("DR-MOCK-")
    assert receipt["verdict"] == "PASS"

    captured = capsys.readouterr()
    assert "Mode:   Offline (mock agents, no API keys needed)" in captured.out
    assert "package unavailable" not in captured.out
    assert "Receipt saved:" in captured.out
