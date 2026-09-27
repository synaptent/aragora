"""Promotion-gate E2E coverage for the truthful default debate loop."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from aragora.cli.commands.quickstart import cmd_quickstart
from aragora.config.feature_flags import get_flag_registry, is_enabled, reset_flag_registry


def _require_truthful_default_loop_flag() -> None:
    """Skip the promotion lane unless the initiative gate is explicitly enabled."""
    if not is_enabled("truthful_default_loop_v1"):
        pytest.skip("truthful_default_loop_v1 disabled")


@pytest.fixture(autouse=True)
def _reset_feature_flags() -> None:
    reset_flag_registry()
    yield
    reset_flag_registry()


def test_truthful_default_loop_gate_skips_when_disabled() -> None:
    """The promotion test must remain opt-in until the rollout flag is enabled."""
    registry = get_flag_registry()

    assert registry.is_registered("truthful_default_loop_v1") is True
    assert is_enabled("truthful_default_loop_v1") is False

    with pytest.raises(pytest.skip.Exception, match="truthful_default_loop_v1 disabled"):
        _require_truthful_default_loop_flag()


@pytest.mark.e2e
def test_truthful_default_loop_provider_block_and_receipt_surface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Blocked live providers must stay truthful through fallback, receipt, and CLI surfaces."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ARAGORA_TRUTHFUL_DEFAULT_LOOP_V1", "true")
    reset_flag_registry()
    _require_truthful_default_loop_flag()

    args = argparse.Namespace(
        question="Should the truthful default loop stay promotion-ready?",
        demo=False,
        provider="openai",
        api_key="sk-inline-test",
        save_key=False,
        output=None,
        format="json",
        json=False,
        rounds=1,
        no_browser=True,
        spec_first=False,
    )

    with patch(
        "aragora.cli.commands.quickstart._can_reach_provider_tls",
        new=AsyncMock(return_value=(False, "connection refused")),
    ):
        cmd_quickstart(args)

    artifact_path = tmp_path / ".aragora" / "receipts" / "quickstart-demo-receipt.json"
    assert artifact_path.exists()
    saved = json.loads(artifact_path.read_text(encoding="utf-8"))

    provider_path = saved["provider_path"]
    assert provider_path["blocked"] is True
    assert provider_path["config_present"] is True
    assert provider_path["live_ready"] is False
    assert provider_path["reason"] == "providers_unreachable"
    assert provider_path["next_action"]

    assert saved["mode"] == "demo"
    assert saved["simulation_label"] == "mock/simulated"
    assert saved["simulated"] is True
    assert saved["fallback"]["label"] == "mock/simulated"
    assert saved["debate_status"] == "completed"
    assert saved["debate_status_source"] == "synthetic"
    assert saved["synthetic"] is True

    assert saved["receipt_id"] == saved["receipt"]["id"]
    assert saved["debate_id"] == saved["receipt_id"]
    assert saved["gauntlet_id"] == saved["receipt_id"]
    assert saved["receipt"]["participants"] == saved["agents"]
    assert saved["receipt"]["consensus_reached"] == saved["consensus_reached"]
    assert saved["artifact_hash"] == saved["checksum"]
    assert saved["artifact_hash"] == saved["receipt"]["artifact_hash"]

    output = capsys.readouterr().out
    assert "Live provider preflight could not verify reachability" in output
    assert "Simulation: mock/simulated" in output
    assert "Next:" in output
    assert f"Receipt:    {saved['receipt_id']}" in output
