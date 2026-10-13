from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts.nomic.phases.context import ContextPhase


def _agent(result: str) -> MagicMock:
    agent = MagicMock()
    agent.generate = AsyncMock(return_value=result)
    return agent


def test_gather_with_default_print_log_and_no_stream_emit(capsys: pytest.CaptureFixture) -> None:
    phase = ContextPhase(aragora_path=Path("."), claude_agent=None, codex_agent=None)

    name, harness, content = asyncio.run(
        phase._gather_with_agent(_agent("explored"), "claude", "Claude Code")
    )

    assert (name, harness, content) == ("claude", "Claude Code", "explored")
    out = capsys.readouterr().out
    assert "  claude (Claude Code): exploring codebase..." in out
    assert "  claude: complete (8 chars)" in out


def test_gather_with_logger_info_log_fn(caplog: pytest.LogCaptureFixture) -> None:
    log = logging.getLogger("test_nomic_context_phase_logging")
    phase = ContextPhase(
        aragora_path=Path("."), claude_agent=None, codex_agent=None, log_fn=log.info
    )

    with caplog.at_level(logging.INFO, logger=log.name):
        _, _, content = asyncio.run(phase._gather_with_agent(_agent("ok"), "codex", "Codex CLI"))

    assert content == "ok"
    assert "  codex: complete (2 chars)" in caplog.messages


def test_gather_error_path_logs_with_message_only_log_fn() -> None:
    messages: list[str] = []
    agent = MagicMock()
    agent.generate = AsyncMock(side_effect=RuntimeError("boom"))
    phase = ContextPhase(
        aragora_path=Path("."), claude_agent=None, codex_agent=None, log_fn=messages.append
    )

    _, _, content = asyncio.run(phase._gather_with_agent(agent, "claude", "Claude Code"))

    assert content == "Error: boom"
    assert messages[-1] == "  claude: error - boom"
