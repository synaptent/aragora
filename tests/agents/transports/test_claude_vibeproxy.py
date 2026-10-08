from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import cast

import pytest

from aragora.agents.transports.claude_vibeproxy import (
    VIBEPROXY_HARNESS,
    VIBEPROXY_TIMEOUT_ENV,
    run_claude_vibeproxy,
)
from aragora.agents.transports.vibeproxy import (
    ModelTransportPolicy,
    TransportMode,
    VibeProxyCatalog,
    VibeProxyClient,
)


@dataclass
class FakeClient:
    models: frozenset[str] = frozenset({"claude-opus-5"})
    base_url: str = "http://127.0.0.1:8318/v1"
    calls: list[dict[str, object]] = field(default_factory=list)

    def catalog(self, *, timeout: float | None = None) -> VibeProxyCatalog:
        return VibeProxyCatalog(models=self.models, fetched_at=0.0)

    def anthropic_message(self, **kwargs: object) -> str:
        self.calls.append(dict(kwargs))
        return "Verdict: PASS"


def _policy(mode: TransportMode, client: FakeClient) -> ModelTransportPolicy:
    return ModelTransportPolicy(mode, client=cast(VibeProxyClient, client))


def test_direct_mode_does_not_touch_vibeproxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(VIBEPROXY_TIMEOUT_ENV, "invalid-but-unused")
    client = FakeClient()
    policy = _policy(TransportMode.DIRECT, client)

    result = run_claude_vibeproxy("prompt", reviewer_timeout=600, policy=policy)

    assert result.attempted is False
    assert result.ok is False
    assert client.calls == []


def test_prefer_mode_runs_exact_model_and_discloses_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(VIBEPROXY_TIMEOUT_ENV, "30")
    client = FakeClient()
    policy = _policy(TransportMode.PREFER, client)

    result = run_claude_vibeproxy("review prompt", reviewer_timeout=600, policy=policy)

    assert result.ok is True
    assert result.required is False
    assert result.text == "Verdict: PASS"
    assert result.response_model == "claude-opus-5"
    assert result.harness == f"{VIBEPROXY_HARNESS} (model: claude-opus-5)"
    assert result.timeout_seconds == 30.0
    # Message leg gets the budget minus the discovery cap (30 - 6), so the two
    # legs sum to at most the attempt budget rather than each drawing the full 30.
    assert client.calls == [
        {
            "model": "claude-opus-5",
            "prompt": "review prompt",
            "timeout": 24.0,
        }
    ]


def test_prefer_mode_reserves_half_the_reviewer_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(VIBEPROXY_TIMEOUT_ENV, "500")
    client = FakeClient()
    policy = _policy(TransportMode.PREFER, client)

    result = run_claude_vibeproxy("prompt", reviewer_timeout=80, policy=policy)

    assert result.ok is True
    # Attempt budget is half the reviewer budget (40); the message leg gets that
    # minus the 6s discovery cap, and the two legs never sum above the budget.
    assert result.timeout_seconds == 40.0
    assert client.calls[0]["timeout"] == 34.0


def test_prefer_mode_allows_direct_fallback_when_model_is_unavailable() -> None:
    policy = _policy(
        TransportMode.PREFER,
        FakeClient(models=frozenset()),
    )

    result = run_claude_vibeproxy("prompt", reviewer_timeout=600, policy=policy)

    assert result.attempted is True
    assert result.required is False
    assert result.ok is False
    assert result.error == "model not in VibeProxy catalog: claude-opus-5"


def test_required_mode_fails_closed_when_model_is_unavailable() -> None:
    policy = _policy(
        TransportMode.REQUIRED,
        FakeClient(models=frozenset()),
    )

    result = run_claude_vibeproxy("prompt", reviewer_timeout=600, policy=policy)

    assert result.attempted is True
    assert result.required is True
    assert result.ok is False
    assert result.error == "model not in VibeProxy catalog: claude-opus-5"


def test_unexpected_resolve_failure_is_sanitized_and_allows_prefer_fallback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "vibeproxy-token-must-not-leak"
    policy = _policy(TransportMode.PREFER, FakeClient())

    def fail_resolve(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(secret)

    monkeypatch.setattr(policy, "resolve", fail_resolve)
    monkeypatch.setenv(VIBEPROXY_TIMEOUT_ENV, "30")

    with caplog.at_level(
        logging.WARNING,
        logger="aragora.agents.transports.claude_vibeproxy",
    ):
        result = run_claude_vibeproxy("prompt", reviewer_timeout=600, policy=policy)

    assert result.attempted is True
    assert result.required is False
    assert result.ok is False
    assert result.error == "Unexpected VibeProxy failure: RuntimeError"
    assert "RuntimeError" in caplog.text
    assert secret not in result.error
    assert secret not in caplog.text
    assert result.timeout_seconds == 30.0
    assert result.elapsed_seconds >= 0.0


def test_unexpected_client_failure_is_sanitized_and_required_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "provider-response-must-not-leak"
    client = FakeClient()
    policy = _policy(TransportMode.REQUIRED, client)

    def fail_message(**_kwargs: object) -> str:
        raise ValueError(secret)

    monkeypatch.setattr(client, "anthropic_message", fail_message)
    monkeypatch.setenv(VIBEPROXY_TIMEOUT_ENV, "30")

    result = run_claude_vibeproxy("prompt", reviewer_timeout=600, policy=policy)

    assert result.attempted is True
    assert result.required is True
    assert result.ok is False
    assert result.error == "Unexpected VibeProxy failure: ValueError"
    assert secret not in result.error
    assert result.timeout_seconds == 30.0
    assert result.elapsed_seconds >= 0.0


def test_invalid_timeout_degrades_to_default_not_required(monkeypatch: pytest.MonkeyPatch) -> None:
    # A malformed timeout env is a tuning typo, not a transport-intent signal:
    # it must NOT escalate prefer -> required or suppress fallback. It degrades
    # to the default budget instead (min(120 default, 600/2 half) == 120).
    monkeypatch.setenv(VIBEPROXY_TIMEOUT_ENV, "not-a-number")
    policy = _policy(TransportMode.PREFER, FakeClient())

    result = run_claude_vibeproxy("prompt", reviewer_timeout=600, policy=policy)

    assert result.required is False
    assert result.ok is True
    assert result.timeout_seconds == 120.0


def test_invalid_timeout_in_required_mode_still_uses_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(VIBEPROXY_TIMEOUT_ENV, "120s")  # unit suffix -> unparseable
    policy = _policy(TransportMode.REQUIRED, FakeClient())

    result = run_claude_vibeproxy("prompt", reviewer_timeout=600, policy=policy)

    assert result.required is True
    assert result.ok is True
    assert result.timeout_seconds == 120.0


def test_bad_transport_env_degrades_to_direct_when_not_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # from_env() fails on a typo'd ARAGORA_MODEL_TRANSPORT; with no explicit
    # required intent the Claude leg degrades to direct (attempted=False) rather
    # than failing closed with all fallbacks suppressed.
    monkeypatch.setenv("ARAGORA_MODEL_TRANSPORT", "vibeproxy-prefre")  # typo

    result = run_claude_vibeproxy("prompt", reviewer_timeout=600, policy=None)

    assert result.attempted is False
    assert result.required is False


def test_bad_transport_env_fails_closed_only_when_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARAGORA_MODEL_TRANSPORT", "vibeproxy-required")
    monkeypatch.setenv("ARAGORA_VIBEPROXY_MODEL_MAP", "{bad")  # from_env raises

    result = run_claude_vibeproxy("prompt", reviewer_timeout=600, policy=None)

    assert result.attempted is True
    assert result.required is True
    assert result.ok is False
