"""Per-agent logging in ContextPhase._gather_with_agent works with any log_fn shape."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.nomic.phases.context import ContextPhase


def _agent(result: str) -> MagicMock:
    agent = MagicMock()
    agent.generate = AsyncMock(return_value=result)
    agent.timeout = 30
    return agent


def test_default_print_log_and_default_stream_emit(capsys: pytest.CaptureFixture[str]) -> None:
    phase = ContextPhase(aragora_path=Path("."), claude_agent=None, codex_agent=None)

    result = asyncio.run(phase._gather_with_agent(_agent("explored"), "claude", "Claude Code"))

    assert result == ("claude", "Claude Code", "explored")
    out = capsys.readouterr().out
    assert "  claude (Claude Code): exploring codebase..." in out
    assert "  claude: complete (8 chars)" in out


def test_logger_info_log_fn(caplog: pytest.LogCaptureFixture) -> None:
    log = logging.getLogger("test_context_phase_logging")
    phase = ContextPhase(
        aragora_path=Path("."),
        claude_agent=None,
        codex_agent=None,
        log_fn=log.info,
        stream_emit_fn=lambda *args, **kwargs: None,
    )

    with caplog.at_level(logging.INFO, logger=log.name):
        _, _, content = asyncio.run(phase._gather_with_agent(_agent("ok"), "codex", "Codex CLI"))

    assert content == "ok"
    assert "  codex (Codex CLI): exploring codebase..." in caplog.messages
    assert "  codex: complete (2 chars)" in caplog.messages


def test_message_only_log_fn_on_error_path() -> None:
    messages: list[str] = []
    agent = _agent("")
    agent.generate = AsyncMock(side_effect=RuntimeError("boom"))
    phase = ContextPhase(
        aragora_path=Path("."), claude_agent=None, codex_agent=None, log_fn=messages.append
    )

    _, _, content = asyncio.run(phase._gather_with_agent(agent, "claude", "Claude Code"))

    assert content == "Error: RuntimeError: boom"
    assert messages[-1] == "  claude: error - RuntimeError: boom"


def test_agent_aware_log_fn_still_receives_agent() -> None:
    calls: list[tuple[str, str | None]] = []

    def log_fn(message: str, also_print: bool = True, agent: str | None = None) -> None:
        calls.append((message, agent))

    phase = ContextPhase(
        aragora_path=Path("."),
        claude_agent=None,
        codex_agent=None,
        log_fn=log_fn,
        stream_emit_fn=lambda *args, **kwargs: None,
    )

    asyncio.run(phase._gather_with_agent(_agent("done"), "gemini", "Kilo Code"))

    assert ("  gemini (Kilo Code): exploring codebase...", "gemini") in calls
    assert ("  gemini: complete (4 chars)", "gemini") in calls
