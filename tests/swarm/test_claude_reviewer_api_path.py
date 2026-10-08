"""The `claude` merge-gate reviewer must fall back to the direct Anthropic API
when the subscription CLI is unavailable but ANTHROPIC_API_KEY is set (e.g. CI
runners with no claude CLI). This lets the gate form a western-family quorum
from API keys alone, without depending on OpenRouter."""

from __future__ import annotations

import pytest

import aragora.swarm.quorum_evidence as qe
from aragora.swarm.quorum_evidence import ReviewerResult


@pytest.fixture(autouse=True)
def _pin_direct_transport(monkeypatch):
    # These tests exercise the CLI/API fallback, not the VibeProxy transport.
    # Pin direct so an ambient ARAGORA_MODEL_TRANSPORT=vibeproxy-prefer (the env
    # this feature documents enabling) cannot make them build a real client or
    # hit the network.
    monkeypatch.setenv("ARAGORA_MODEL_TRANSPORT", "direct")


def _cli_ok(_prompt, *, timeout=None):
    return ReviewerResult("claude", "CLI verdict: PASS", True)


def _cli_missing(_prompt, *, timeout=None):
    return ReviewerResult("claude", "", False, "claude CLI not found on PATH")


def test_cli_success_does_not_call_api(monkeypatch):
    monkeypatch.setattr(qe, "_run_claude_cli", _cli_ok)

    def _boom(*_a, **_k):
        raise AssertionError("API must not be called when the CLI succeeds")

    monkeypatch.setattr(qe, "_run_api_agent", _boom)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    result = qe._run_claude_reviewer("prompt")
    assert result.ok
    assert result.text == "CLI verdict: PASS"


def test_cli_failure_with_key_uses_anthropic_api(monkeypatch):
    monkeypatch.setattr(qe, "_run_claude_cli", _cli_missing)
    calls = {}

    def _api(family, prompt):
        calls["family"] = family
        return ReviewerResult("anthropic-api", "API verdict: PASS", True)

    monkeypatch.setattr(qe, "_run_api_agent", _api)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    result = qe._run_claude_reviewer("prompt")
    assert result.ok
    assert result.text == "API verdict: PASS"
    # transport uses the Anthropic API agent type, relabelled to the claude family
    assert calls["family"] == "anthropic-api"
    assert result.family == "claude"


def test_cli_failure_without_key_does_not_call_api(monkeypatch):
    monkeypatch.setattr(qe, "_run_claude_cli", _cli_missing)

    def _boom(*_a, **_k):
        raise AssertionError("API must not be called without ANTHROPIC_API_KEY")

    monkeypatch.setattr(qe, "_run_api_agent", _boom)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = qe._run_claude_reviewer("prompt")
    assert not result.ok
    assert "CLI not found" in result.error


def test_cli_and_api_both_fail_returns_failure(monkeypatch):
    # So the generic OpenRouter fallback in default_reviewer_runner still fires.
    monkeypatch.setattr(qe, "_run_claude_cli", _cli_missing)
    monkeypatch.setattr(
        qe,
        "_run_api_agent",
        lambda *_a, **_k: ReviewerResult("claude", "", False, "AnthropicError: 401"),
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    result = qe._run_claude_reviewer("prompt")
    assert not result.ok


def test_default_runner_routes_claude_through_reviewer(monkeypatch):
    monkeypatch.setattr(qe, "_run_claude_cli", _cli_missing)
    monkeypatch.setattr(
        qe, "_run_api_agent", lambda *_a, **_k: ReviewerResult("claude", "API ok", True)
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    result = qe.default_reviewer_runner("claude", "prompt")
    assert result.ok
    assert result.text == "API ok"
