"""Debate-completed event: the debate engine emits it, aragora.analytics subscribes."""

from __future__ import annotations

import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from aragora.events import debate_completion
from aragora.events.debate_completion import (
    AgentActivity,
    DebateCompletedEvent,
    DebateCompletedNotSubscribedError,
    emit_debate_completed,
    registered_count,
    subscribe_debate_completed,
    unsubscribe_debate_completed,
)
from aragora.utils.declared_registrations import DeclaredRegistrations

REPO_ROOT = Path(__file__).resolve().parents[2]

_EVENT = DebateCompletedEvent(
    debate_id="debate-1",
    task="Plan a release",
    rounds=2,
    consensus_reached=True,
    duration_seconds=3.5,
    agents=("alpha", "beta"),
    status="completed",
    org_id="org-1",
    user_id="user-1",
    protocol="majority",
    total_messages=4,
    total_votes=2,
    total_cost=Decimal("0.25"),
    agent_activity=(
        AgentActivity(
            agent_id="alpha",
            response_time_ms=12.0,
            tokens_in=10,
            tokens_out=5,
            cost=Decimal("0.1"),
            provider="anthropic",
            model="claude",
        ),
    ),
)


@pytest.fixture
def isolated_hook(monkeypatch: pytest.MonkeyPatch) -> dict:
    """No subscribers, and the declared subscriptions count as already run."""
    subscribers: dict = {}
    monkeypatch.setattr(debate_completion, "_subscribers", subscribers)
    declared = DeclaredRegistrations(debate_completion.DEBATE_COMPLETED_ENTRY_POINT_GROUP)
    monkeypatch.setattr(declared, "load", lambda: None)
    monkeypatch.setattr(debate_completion, "_declared", declared)
    return subscribers


async def test_emit_without_subscribers_raises(isolated_hook: dict) -> None:
    with pytest.raises(DebateCompletedNotSubscribedError, match="aragora.analytics"):
        await emit_debate_completed(_EVENT)


async def test_subscribers_receive_the_event_once_per_name(isolated_hook: dict) -> None:
    received: list[DebateCompletedEvent] = []

    async def handler(event: DebateCompletedEvent) -> None:
        received.append(event)

    subscribe_debate_completed("test", handler)
    subscribe_debate_completed("test", handler)
    assert registered_count() == 1

    assert await emit_debate_completed(_EVENT) == 1
    assert received == [_EVENT]
    assert received[0].event_type == "debate_completed"

    assert unsubscribe_debate_completed("test") is True
    assert unsubscribe_debate_completed("test") is False
    assert registered_count() == 0


async def test_failing_subscriber_does_not_stop_the_others(isolated_hook: dict) -> None:
    received: list[str] = []

    async def broken(event: DebateCompletedEvent) -> None:
        raise RuntimeError("store unavailable")

    async def working(event: DebateCompletedEvent) -> None:
        received.append(event.debate_id)

    subscribe_debate_completed("broken", broken)
    subscribe_debate_completed("working", working)

    assert await emit_debate_completed(_EVENT) == 1
    assert received == ["debate-1"]


async def test_first_emit_runs_declared_subscriptions(
    isolated_hook: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "aragora"\n'
        '[project.entry-points."aragora.debate_completed_subscribers"]\n'
        'analytics = "aragora.analytics.debate_events:subscribe_debate_analytics"\n',
        encoding="utf-8",
    )
    declared = DeclaredRegistrations(
        debate_completion.DEBATE_COMPLETED_ENTRY_POINT_GROUP, source_pyproject=pyproject
    )
    monkeypatch.setattr(debate_completion, "_declared", declared)
    analytics = SimpleNamespace(record_debate=AsyncMock(), record_agent_activity=AsyncMock())

    with patch("aragora.analytics.debate_analytics.get_debate_analytics", return_value=analytics):
        assert await emit_debate_completed(_EVENT) == 1
        assert await emit_debate_completed(_EVENT) == 1

    assert declared.loaded
    assert list(isolated_hook) == ["aragora.analytics.debate_analytics"]
    assert analytics.record_debate.await_count == 2


async def test_analytics_subscriber_records_debate_and_agent_activity(isolated_hook: dict) -> None:
    from aragora.analytics.debate_events import subscribe_debate_analytics

    subscribe_debate_analytics()
    analytics = SimpleNamespace(record_debate=AsyncMock(), record_agent_activity=AsyncMock())

    with patch("aragora.analytics.debate_analytics.get_debate_analytics", return_value=analytics):
        await emit_debate_completed(_EVENT)

    analytics.record_debate.assert_awaited_once_with(
        debate_id="debate-1",
        rounds=2,
        consensus_reached=True,
        duration_seconds=3.5,
        agents=["alpha", "beta"],
        status="completed",
        org_id="org-1",
        user_id="user-1",
        protocol="majority",
        total_messages=4,
        total_votes=2,
        total_cost=Decimal("0.25"),
    )
    analytics.record_agent_activity.assert_awaited_once_with(
        agent_id="alpha",
        debate_id="debate-1",
        response_time_ms=12.0,
        tokens_in=10,
        tokens_out=5,
        cost=Decimal("0.1"),
        error=False,
        agent_name="alpha",
        provider="anthropic",
        model="claude",
    )


async def test_offline_demo_debate_emits_one_event(isolated_hook: dict) -> None:
    from aragora.debate.api import debate

    received: list[DebateCompletedEvent] = []

    async def handler(event: DebateCompletedEvent) -> None:
        received.append(event)

    subscribe_debate_completed("test", handler)

    result = await debate("se2 offline probe", agents=2, rounds=1)

    assert len(received) == 1
    assert received[0].task == "se2 offline probe"
    assert received[0].debate_id
    assert received[0].agents == ("agent-1", "agent-2")
    assert result.task == "se2 offline probe"


def test_analytics_package_registers_once() -> None:
    code = (
        "import importlib\n"
        "from aragora.events import debate_completion as hook\n"
        "assert hook.registered_count() == 0\n"
        "import aragora.analytics\n"
        "assert list(hook._subscribers) == ['aragora.analytics.debate_analytics'], hook._subscribers\n"
        "importlib.reload(aragora.analytics)\n"
        "assert hook.registered_count() == 1\n"
        "print('REGISTERED')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO_ROOT, timeout=300
    )
    assert proc.returncode == 0, proc.stderr
    assert "REGISTERED" in proc.stdout
