"""Tests for CLI demo with real model support."""

from __future__ import annotations

import argparse
from unittest.mock import patch, MagicMock

import pytest


def test_demo_prefers_real_debate_when_openrouter_key_set():
    """When OPENROUTER_API_KEY is available, demo should run a real debate."""
    from aragora.cli.demo import main

    args = argparse.Namespace(
        name=None,
        topic="Should we use Rust?",
        list_demos=False,
        server=False,
        receipt=None,
        offline=False,
    )

    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
        with patch("aragora.cli.demo._run_real_demo") as mock_real:
            mock_real.return_value = None
            main(args)
            mock_real.assert_called_once_with("Should we use Rust?", receipt_path=None)


def test_demo_passes_receipt_path_to_real_debate():
    """Real demo path preserves --receipt instead of dropping it."""
    from aragora.cli.demo import main

    args = argparse.Namespace(
        name=None,
        topic="Should we use Rust?",
        list_demos=False,
        server=False,
        receipt="receipt.md",
        offline=False,
    )

    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
        with patch("aragora.cli.demo._run_real_demo") as mock_real:
            mock_real.return_value = None
            main(args)
            mock_real.assert_called_once_with("Should we use Rust?", receipt_path="receipt.md")


def test_demo_offline_flag_uses_mock():
    """--offline flag should always use mock, even with API keys."""
    from aragora.cli.demo import main

    args = argparse.Namespace(
        name=None,
        topic="test",
        list_demos=False,
        server=False,
        receipt=None,
        offline=True,
    )

    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
        with patch("aragora.cli.demo._run_mock_demo") as mock_fn:
            mock_fn.return_value = None
            main(args)
            mock_fn.assert_called_once()


def test_demo_no_keys_falls_back_to_mock():
    """Without any API keys, fall back to mock with a message."""
    from aragora.cli.demo import main

    args = argparse.Namespace(
        name=None,
        topic="test",
        list_demos=False,
        server=False,
        receipt=None,
        offline=False,
    )

    with patch("aragora.cli.demo._has_any_api_key", return_value=False):
        with patch("aragora.cli.demo._run_mock_demo") as mock_fn:
            mock_fn.return_value = None
            main(args)
            mock_fn.assert_called_once()


def test_has_any_api_key_returns_true_for_openrouter():
    """_has_any_api_key should detect OPENROUTER_API_KEY."""
    from aragora.cli.demo import _has_any_api_key

    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-or-test"}, clear=False):
        assert _has_any_api_key() is True


def test_has_any_api_key_returns_true_for_anthropic():
    """_has_any_api_key should detect ANTHROPIC_API_KEY."""
    from aragora.cli.demo import _has_any_api_key

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-test"}, clear=False):
        assert _has_any_api_key() is True


def test_has_any_api_key_returns_false_when_empty():
    """_has_any_api_key should return False when no keys are set."""
    from aragora.cli.demo import _has_any_api_key

    env = {
        "OPENROUTER_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "OPENAI_API_KEY": "",
    }
    with patch.dict("os.environ", env, clear=False):
        assert _has_any_api_key() is False


def test_demo_list_still_works():
    """--list flag should still list demos regardless of API key state."""
    from aragora.cli.demo import main

    args = argparse.Namespace(
        name=None,
        topic=None,
        list_demos=True,
        server=False,
        receipt=None,
        offline=False,
    )

    # Should not raise, and should not try to run any debate
    with patch("aragora.cli.demo._run_real_demo") as mock_real:
        with patch("aragora.cli.demo._run_mock_demo") as mock_mock:
            main(args)
            mock_real.assert_not_called()
            mock_mock.assert_not_called()


def test_run_real_demo_calls_playground(capsys):
    """_run_real_demo should call start_playground_debate."""
    from aragora.cli.demo import _run_real_demo

    mock_result = {
        "status": "completed",
        "consensus_reached": True,
        "confidence": 0.85,
        "participants": ["analyst", "critic", "synthesizer"],
        "proposals": {"analyst": "We should use Rust for safety."},
        "final_answer": "Rust offers memory safety benefits.",
    }

    # Patch at the source module — _run_real_demo does a lazy import from there
    with patch(
        "aragora.server.handlers.playground.start_playground_debate",
        return_value=mock_result,
    ):
        _run_real_demo("Should we use Rust?")

    captured = capsys.readouterr()
    assert "Real AI Debate" in captured.out
    assert "Should we use Rust?" in captured.out
    assert "completed" in captured.out
    assert "85%" in captured.out
