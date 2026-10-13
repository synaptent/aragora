"""A rejected mounted provider key stays isolated to its own provider.

One non-conforming file in ``ARAGORA_SECRETS_DIR`` fails reads of its own name
only. The agents availability and health endpoints must keep answering for every
other provider and report the affected one as rejected: not as missing, not
through an alias or an environment copy, and not through an OpenRouter fallback.
A debate that requests the affected provider must end in a recorded error instead
of dying in its thread.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from aragora.config import secrets as secrets_module

_PROVIDER_NAMES = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "XAI_API_KEY",
    "GROK_API_KEY",
    "MISTRAL_API_KEY",
)
_MOUNTED_VALUE = "synthetic-mounted-provider-value-0000000000"
_ENV_VALUE = "synthetic-environment-provider-value-000000"


@pytest.fixture
def mount_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., Path]]:
    """Serve synthetic provider keys from a protected mounted directory."""
    for name in _PROVIDER_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("ARAGORA_SECRETS_STRICT", raising=False)
    monkeypatch.setenv("ARAGORA_ENV", "development")
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")

    def mount(**modes: int) -> Path:
        directory = tmp_path / "secrets"
        directory.mkdir()
        directory.chmod(0o700)
        for name, mode in modes.items():
            path = directory / name
            path.write_text(_MOUNTED_VALUE)
            path.chmod(mode)
        monkeypatch.setenv("ARAGORA_SECRETS_DIR", str(directory))
        secrets_module.reset_secret_manager()
        return directory

    secrets_module.reset_secret_manager()
    yield mount
    secrets_module.reset_secret_manager()


def _http_handler() -> MagicMock:
    request = MagicMock()
    request.client_address = ("127.0.0.1", 54321)
    request.headers = {}
    return request


async def _get(path: str) -> tuple[int, dict[str, Any], str]:
    from aragora.server.handlers.agents.agents import AgentsHandler

    result = await AgentsHandler(server_context={}).handle(path, {}, _http_handler())
    raw = result.body.decode() if isinstance(result.body, bytes) else str(result.body)
    return result.status_code, json.loads(raw), raw


def _assert_redacted(text: str, directory: Path) -> None:
    assert _MOUNTED_VALUE not in text
    assert _ENV_VALUE not in text
    assert str(directory) not in text


@pytest.mark.asyncio
async def test_availability_reports_a_rejected_key_as_rejected_without_fallback(
    mount_keys: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = mount_keys(
        ANTHROPIC_API_KEY=0o600,
        OPENAI_API_KEY=0o644,
        OPENROUTER_API_KEY=0o600,
        GEMINI_API_KEY=0o644,
        GOOGLE_API_KEY=0o600,
    )
    monkeypatch.setenv("OPENAI_API_KEY", _ENV_VALUE)

    status, body, raw = await _get("/api/agents/availability")

    assert status == 200
    assert body["openrouter_available"] is True
    assert body["openrouter_rejected"] is False
    openai = body["agents"]["openai-api"]
    assert openai["available"] is False
    assert openai["rejected_env_vars"] == ["OPENAI_API_KEY"]
    assert openai["missing_env_vars"] == []
    assert openai["uses_openrouter_fallback"] is False
    assert openai["fallback_model"] is None
    gemini = body["agents"]["gemini"]
    assert gemini["available"] is False
    assert gemini["rejected_env_vars"] == ["GEMINI_API_KEY"]
    assert gemini["uses_openrouter_fallback"] is False
    for unaffected in ("anthropic-api", "deepseek"):
        assert body["agents"][unaffected]["available"] is True
        assert body["agents"][unaffected]["rejected_env_vars"] == []
    _assert_redacted(raw, directory)


@pytest.mark.asyncio
async def test_health_reports_a_rejected_key_and_keeps_other_providers_available(
    mount_keys: Callable[..., Path],
) -> None:
    directory = mount_keys(ANTHROPIC_API_KEY=0o600, OPENAI_API_KEY=0o644, OPENROUTER_API_KEY=0o600)

    status, body, raw = await _get("/api/agents/health")

    assert status == 200
    assert body["fallback"]["openrouter_available"] is True
    assert body["fallback"]["openrouter_rejected"] is False
    openai = body["agents"]["openai-api"]
    assert openai["available"] is False
    assert openai["api_key_configured"] is False
    assert openai["api_key_rejected"] is True
    assert openai["rejected_env_vars"] == ["OPENAI_API_KEY"]
    assert openai.get("uses_openrouter_fallback") is not True
    assert openai.get("fallback_model") is None
    anthropic = body["agents"]["anthropic-api"]
    assert anthropic["available"] is True
    assert anthropic["api_key_rejected"] is False
    assert body["agents"]["deepseek"]["available"] is True
    _assert_redacted(raw, directory)


@pytest.mark.asyncio
async def test_a_rejected_openrouter_key_is_reported_rejected_not_missing(
    mount_keys: Callable[..., Path],
) -> None:
    directory = mount_keys(OPENAI_API_KEY=0o600, OPENROUTER_API_KEY=0o644)

    status, body, raw = await _get("/api/agents/availability")

    assert status == 200
    assert body["openrouter_available"] is False
    assert body["openrouter_rejected"] is True
    deepseek = body["agents"]["deepseek"]
    assert deepseek["available"] is False
    assert deepseek["rejected_env_vars"] == ["OPENROUTER_API_KEY"]
    assert deepseek["missing_env_vars"] == []
    anthropic = body["agents"]["anthropic-api"]
    assert anthropic["missing_env_vars"] == ["ANTHROPIC_API_KEY"]
    assert anthropic["available"] is False
    assert body["agents"]["openai-api"]["available"] is True
    _assert_redacted(raw, directory)

    status, health, raw = await _get("/api/agents/health")

    assert status == 200
    assert health["fallback"]["openrouter_available"] is False
    assert health["fallback"]["openrouter_rejected"] is True
    _assert_redacted(raw, directory)


def _run_debate(
    monkeypatch: pytest.MonkeyPatch, agents: str, create_agents: MagicMock
) -> tuple[dict[str, Any], list[Any]]:
    import threading

    from aragora.server.stream import debate_executor

    debates: dict[str, dict[str, Any]] = {"rejected-key-debate": {"status": "starting"}}
    monkeypatch.setattr(debate_executor, "_active_debates", debates)
    monkeypatch.setattr(debate_executor, "_active_debates_lock", threading.Lock())
    monkeypatch.setattr(debate_executor, "_create_debate_agents", create_agents)
    emitter = MagicMock()

    debate_executor.execute_debate_thread(
        debate_id="rejected-key-debate",
        question="Synthetic question",
        agents_str=agents,
        rounds=1,
        consensus="majority",
        trending_topic=None,
        emitter=emitter,
    )

    return debates["rejected-key-debate"], [call.args[0] for call in emitter.emit.call_args_list]


def test_a_debate_requesting_a_rejected_provider_ends_in_a_recorded_error(
    mount_keys: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = mount_keys(ANTHROPIC_API_KEY=0o600, OPENAI_API_KEY=0o644, OPENROUTER_API_KEY=0o600)
    create_agents = MagicMock(return_value=[])

    debate, events = _run_debate(monkeypatch, "anthropic-api,openai-api", create_agents)

    assert debate["status"] == "error"
    assert "openai-api" in debate["error"]
    assert "OPENAI_API_KEY" in debate["error"]
    create_agents.assert_not_called()
    kinds = [(event.type.value, event.data.get("error_type")) for event in events]
    assert ("agent_error", "secret_rejected") in kinds
    assert ("agent_error", "missing_env_fallback") not in kinds
    assert ("error", None) in kinds
    assert "debate_start" not in [kind for kind, _ in kinds]
    _assert_redacted(json.dumps(debate) + repr([event.data for event in events]), directory)


def test_a_debate_without_the_rejected_provider_still_runs_its_requested_agents(
    mount_keys: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    mount_keys(ANTHROPIC_API_KEY=0o600, OPENAI_API_KEY=0o644, OPENROUTER_API_KEY=0o600)
    create_agents = MagicMock(return_value=[])

    _, events = _run_debate(monkeypatch, "anthropic-api,deepseek", create_agents)

    create_agents.assert_called_once()
    assert [spec.provider for spec in create_agents.call_args.args[0]] == [
        "anthropic-api",
        "deepseek",
    ]
    kinds = [(event.type.value, event.data.get("error_type")) for event in events]
    assert ("debate_start", None) in kinds
    assert ("agent_error", "secret_rejected") not in kinds


def test_a_secret_source_error_inside_the_debate_thread_is_recorded(
    mount_keys: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = mount_keys(ANTHROPIC_API_KEY=0o600, OPENAI_API_KEY=0o600)
    reason = f"synthetic custody failure for {directory / 'OPENAI_API_KEY'}"
    create_agents = MagicMock(side_effect=secrets_module.SecretSourceError(reason))

    debate, events = _run_debate(monkeypatch, "anthropic-api,openai-api", create_agents)

    assert debate["status"] == "error"
    assert reason not in debate["error"]
    assert "error" in [event.type.value for event in events]
    _assert_redacted(json.dumps(debate) + repr([event.data for event in events]), directory)
